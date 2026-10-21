import math
import time
from datetime import datetime, timedelta

from telegram.error import TelegramError

from src.coroner.CoronerApi import CoronerInterrupted
from src.coroner.CoronerMessages import duration
from src.coroner.CoronerProtectionModels import (
    CheckObservation, DayObservation, MetricObservation,
    QuarantineCandidate, RemovalReservation, ReviewRequest, ReviewTarget, SafetySignal,
    calendar_timezone,
)


class CoronerProtection:
    """Persistent quarantine and safety decisions. Telegram mutations stay in the service."""

    def __init__(self, service):
        self.service = service
        self._last_collection_at = None
        self._notification_task = None
        self._notification_retry_at = 0
        self.recover()

    @property
    def state(self):
        return self.service.state.protection

    @property
    def config(self):
        return self.service.config.protection

    def changed(self):
        self.service._changed()

    def recover(self):
        now = time.time()
        # Retire persisted evidence and blocks belonging only to the removed detector.
        if self.state.metrics.pop("api", None) is not None:
            self.changed()
        if "api" in self.state.active_rule_keys:
            self.state.active_rule_keys.remove("api")
            self.changed()
        # Old quota incidents used absolute counts; enforce the current percentages
        # again before the next removal instead of retaining obsolete count caps.
        retired = [key for key, signal in self.state.reasons.items()
                   if key == "api" or (signal.kind == "quota" and signal.unit is None)]
        for key in retired:
            del self.state.reasons[key]
        if retired:
            if not self.state.reasons:
                self.state.blocked = False
                request = self.state.requests.get(self.state.current_request_id)
                if request is not None and request.state == "pending":
                    request.state = "superseded"
                    request.decided_at = now
                self.state.current_request_id = None
            self.changed()
        if self.state.day_timezone is None:
            self.state.day_timezone = self.config.day_timezone
            self.changed()
        known = {entry.id for entry in self.state.reservations}
        horizon = max(item.window_seconds for item in self.config.removal_limits)
        for removal in self.service.state.removals:
            if removal.operation_id not in known and removal.removed_at > now - horizon:
                self.state.reservations.append(RemovalReservation(
                    id=removal.operation_id, user_id=removal.user_id, chat_id=removal.chat_id,
                    at=removal.removed_at, chat_population=0, global_population=0,
                    dry_run=False, state="completed",
                ))
                self.changed()
        pending = [entry for entry in self.state.reservations if entry.state == "pending"]
        if pending:
            for entry in pending:
                entry.state = "uncertain"
                entry.at = now
            self.trip(SafetySignal(key="interrupted-removal", kind="interrupted", at=now,
                                   value=len(pending)))

    def day(self, at):
        return datetime.fromtimestamp(at, calendar_timezone(self.config.day_timezone)).date()

    def _day_bounds(self, day):
        zone = calendar_timezone(self.config.day_timezone)
        start = datetime.combine(day, datetime.min.time(), zone).timestamp()
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), zone).timestamp()
        return start, end

    def collect(self, now):
        if self.state.day_timezone != self.config.day_timezone:
            self.state.day_timezone = self.config.day_timezone
            self.state.days.clear()
            self.state.metrics.clear()
            self._last_collection_at = None
            self.changed()
        if self.service.state.status != "running":
            self._last_collection_at = None
            return
        previous = self._last_collection_at
        if previous is not None and now < previous:
            return
        self._last_collection_at = now
        if previous is None or not 0 <= now - previous <= self.config.maximum_collection_gap_seconds:
            return
        cursor = previous
        while cursor < now:
            day = self.day(cursor)
            end = min(now, self._day_bounds(day)[1])
            record = self.state.days.setdefault(day.isoformat(), DayObservation())
            record.coverage_seconds += end - cursor
            cursor = end
        self.changed()

    def record_check(self, user_id, chat_id, result, now=None, *, primary=True):
        now = time.time() if now is None else now
        user = self.service.state.users[user_id]
        recent = user.last_alive_at is not None and now - user.last_alive_at <= self.config.recent_alive_seconds
        self.state.checks.append(CheckObservation(
            user_id=user_id, chat_id=chat_id, at=now,
            result={True: "alive", False: "deleted", None: "unknown"}[result], recently_alive=recent, primary=primary,
        ))
        if result is True:
            user.last_alive_at = now
            self.cancel_candidate(user_id, now)
        self.changed()
        self.evaluate(now)

    def cancel_candidate(self, user_id, now=None):
        if self.state.quarantine.pop(user_id, None) is not None:
            now = time.time() if now is None else now
            self.state.cancelled_candidates.append((now, user_id))
            self.state.rejected_until[user_id] = now + self.config.rejection_cooldown_seconds
            self.changed()

    def observe_activity(self, user_id, sent_at):
        user = self.service.state.users.get(user_id)
        if user is not None and (user.last_alive_at is None or sent_at > user.last_alive_at):
            user.last_alive_at = sent_at
            self.changed()
        candidate = self.state.quarantine.get(user_id)
        if candidate is None or sent_at <= candidate.detected_at:
            return
        now = time.time()
        self.cancel_candidate(user_id, now)
        self.state.activity_conflicts.append((now, user_id))
        recent = {user for at, user in self.state.activity_conflicts
                  if at > now - self.config.activity_window_seconds}
        if len(recent) >= self.config.activity_minimum_users:
            self.trip(SafetySignal(key="candidate-activity", kind="activity", at=now,
                                   value=len(recent), threshold=self.config.activity_minimum_users,
                                   user_id=user_id), new_incident=True)
        user = self.service.state.users.get(user_id)
        if user is not None:
            user.last_alive_at = now
        self.changed()

    def enter(self, job, row, now=None):
        now = time.time() if now is None else now
        if self.state.rejected_until.get(job.user_id, 0) > now:
            return None
        candidate = self.state.quarantine.get(job.user_id)
        if candidate is None:
            candidate = QuarantineCandidate(
                user_id=job.user_id, grade=self.service._user_grade(job.user_id, now).name,
                detected_at=now, ready_at=now + self.config.quarantine_seconds,
            )
            self.state.quarantine[job.user_id] = candidate
            day = self.state.days.setdefault(self.day(now).isoformat(), DayObservation())
            day.candidates.setdefault(job.user_id, candidate.grade)
        candidate.targets[job.chat_id] = row.generation
        self.changed()
        self.evaluate(now)
        return candidate

    def permitted(self, candidate, chat_id, generation, now=None):
        now = time.time() if now is None else now
        if (self.state.quarantine.get(candidate.user_id) is not candidate
                or candidate.targets.get(chat_id) != generation or now < candidate.ready_at):
            return False
        return not self.is_blocked(now) or (
            candidate.approval_epoch == self.state.epoch
            and candidate.approval_expires_at > now
            and candidate.approved_targets.get(chat_id) == generation
        )

    def limits_bypassed(self, now=None):
        now = time.time() if now is None else now
        return now < self.state.removal_limit_bypass_until

    def blocking_reasons(self, now=None):
        return [signal for signal in self.state.reasons.values()
                if signal.kind != "quota" or not self.limits_bypassed(now)]

    def is_blocked(self, now=None):
        return self.state.blocked and (
            not self.state.reasons or bool(self.blocking_reasons(now))
        )

    def bypass_status(self, t):
        if not self.limits_bypassed():
            return t("limit_bypass_off")
        return t("limit_bypass_active", remaining=duration(self.state.removal_limit_bypass_until - time.time()),
                 user_id=self.state.removal_limit_bypass_by)

    async def bypass_limits(self, user_id, *, enabled=True):
        if not self.service._storage_healthy or not self.service._config_healthy:
            return "limit_bypass_failed"
        if enabled and self.limits_bypassed():
            return "limit_bypass_already_active"
        previous = self.state.removal_limit_bypass_until, self.state.removal_limit_bypass_by
        self.state.removal_limit_bypass_until = (
            time.time() + self.config.removal_limit_bypass_seconds if enabled else 0
        )
        self.state.removal_limit_bypass_by = user_id if enabled else None
        if enabled:
            for job in self.service.state.queue.values():
                candidate = self.state.quarantine.get(job.user_id)
                if (candidate is not None and not job.attempts
                        and self.permitted(candidate, job.chat_id, job.generation)):
                    job.not_before = 0
        self.changed()
        if not await self.service.save(force=True):
            self.state.removal_limit_bypass_until, self.state.removal_limit_bypass_by = previous
            self.changed()
            return "limit_bypass_failed"
        self.service.logger.warning("CORONER removal-limit bypass enabled=%s by=%s until=%s",
                                    enabled, user_id, self.state.removal_limit_bypass_until)
        return "limit_bypass_enabled" if enabled else "limit_bypass_disabled"

    def finish_target(self, user_id, chat_id):
        candidate = self.state.quarantine.get(user_id)
        if candidate is None:
            return
        candidate.targets.pop(chat_id, None)
        candidate.approved_targets.pop(chat_id, None)
        if not candidate.targets:
            self.state.quarantine.pop(user_id, None)
        self.changed()

    def trip(self, signal, *, new_incident=False):
        previous = self.state.reasons.get(signal.key)
        if previous is not None and self.state.blocked and not new_incident:
            if previous.value != signal.value or previous.threshold != signal.threshold:
                signal.at = previous.at
                self.state.reasons[signal.key] = signal
                self.changed()
            return
        self.state.blocked = True
        self.state.epoch += 1
        self.state.reasons.pop(signal.key, None)
        self.state.reasons[signal.key] = signal
        self.new_request(signal.at)
        self.service.logger.critical("CORONER QUARANTINE BLOCKED: %s value=%s threshold=%s chat=%s grade=%s",
                                     signal.kind, signal.value, signal.threshold, signal.chat_id, signal.grade)
        self.service._error(None, "protection:" + signal.key, "safety_blocked",
                            reason=self.reason_text(signal))
        self.changed()

    def reason_text(self, signal):
        if signal.kind in ("manual", "population", "interrupted", "budget_history"):
            text = self.service.t("safety_kind_" + signal.kind)
            if signal.user_id is not None:
                text += self.service.t("api_subject", user_id=signal.user_id)
            if signal.chat_id is not None:
                text = self.service.t("error_chat", chat_id=signal.chat_id, text=text)
            return text
        return self.service.t("quota_reason" if signal.kind == "quota" else "safety_reason",
                              kind=self.service.t("safety_kind_" + signal.kind),
                              value=f"{signal.value:g}", threshold=f"{signal.threshold:g}",
                              scope=str(signal.chat_id) if signal.chat_id is not None else (signal.grade or "ALL"))

    def new_request(self, now=None):
        now = time.time() if now is None else now
        old = self.state.requests.get(self.state.current_request_id)
        if old is not None and old.state == "pending":
            old.state = "superseded"
            old.decided_at = now
        request = ReviewRequest(created_at=now, epoch=self.state.epoch, targets={
            user_id: ReviewTarget(candidate_id=candidate.id, targets=dict(candidate.targets),
                                  grade=(self.service._user_grade(user_id, now).name
                                         if user_id in self.service.state.users else candidate.grade))
            for user_id, candidate in self.state.quarantine.items() if candidate.targets
        })
        if old is not None:
            request.notifications = dict(old.notifications)
        self.state.requests[request.id] = request
        self.state.current_request_id = request.id
        self.changed()
        return request

    def approve_request(self, request_id, user_id):
        request = self.state.requests.get(request_id)
        if request is None or request.epoch != self.state.epoch or request.state != "pending":
            return "review_stale"
        now = time.time()
        if not request.targets:
            return "review_no_accounts"
        for target, snapshot in request.targets.items():
            candidate = self.state.quarantine.get(target)
            if candidate is None or candidate.id != snapshot.candidate_id:
                continue
            candidate.approved_targets = {
                chat: generation for chat, generation in snapshot.targets.items()
                if candidate.targets.get(chat) == generation
            }
            candidate.approval_epoch = self.state.epoch
            candidate.approval_expires_at = now + self.config.approval_seconds
            for chat_id, generation in snapshot.targets.items():
                row = self.service.state.participants.get(chat_id, {}).get(target)
                if (row is None or not row.active or row.generation != generation
                        or not self.service.bot_state.is_chat_moderated(chat_id)):
                    continue
                self.service._enqueue(chat_id, target, row, "manual")
                self.service.state.queue[f"{chat_id}:{target}"].not_before = 0
        request.state = "approved"
        request.decided_at, request.decided_by = now, user_id
        self.changed()
        self.service.logger.info("CORONER review %s approved by=%s users=%s", request_id, user_id, list(request.targets))
        return "review_decided"

    def acknowledge(self):
        self.evaluate()
        if self.state.quarantine or self.state.active_rule_keys:
            return "review_cannot_resume"
        self.state.blocked = False
        self.state.reasons.clear()
        self.state.epoch += 1
        self.state.current_request_id = None
        self.changed()
        return "review_resumed"

    @staticmethod
    def _latest(records):
        result = {}
        for record in records:
            result[record.user_id] = record
        return list(result.values())

    def _rate(self, key, kind, rule, records, now, *, chat_id=None, attempts=None):
        samples = len(records)
        matches = sum(record.result == "deleted" for record in records)
        value = 100 * matches / samples if samples else 0
        return dict(key=key, kind=kind, chat_id=chat_id, grade=None, window=rule.window_seconds,
                    samples=samples, matches=matches, minimum=rule.minimum_users,
                    minimum_matches=rule.minimum_matches, value=value, threshold=rule.threshold_percent,
                    enabled=samples >= rule.minimum_users, missing=f"{samples}/{rule.minimum_users}",
                    attempts=len(attempts or []), false_attempts=sum(
                        record.result == "deleted" for record in (attempts or [])),
                    unknown_attempts=sum(record.result == "unknown" for record in (attempts or [])))

    def measurements(self, now=None):
        now = time.time() if now is None else now
        false = self.config.false_results
        valid = [record for record in self.state.checks
                 if record.at > now - false.window_seconds and record.result != "unknown"]
        primary = [record for record in self.state.checks if record.at > now - false.window_seconds and record.primary]
        result = [self._rate("false:global", "false", false, self._latest(valid), now, attempts=primary)]
        grouped = {}
        primary_grouped = {}
        for record in primary:
            primary_grouped.setdefault(record.chat_id, []).append(record)
        for record in valid:
            grouped.setdefault(record.chat_id, []).append(record)
        for chat_id in sorted(set(self.service.bot_state.moderated_chat_ids)):
            result.append(self._rate(f"false:{chat_id}", "false", false,
                                     self._latest(grouped.get(chat_id, [])), now, chat_id=chat_id,
                                     attempts=primary_grouped.get(chat_id, [])))
        transition = self.config.alive_transitions
        recent = self._latest([record for record in self.state.checks
                               if record.at > now - transition.window_seconds
                               and record.recently_alive and record.result != "unknown"])
        result.append(self._rate("transitions", "transitions", transition, recent, now))
        profiles = self.config.profile_inconsistencies
        records = self._latest([record for record in self.state.checks
                                if record.at > now - profiles.window_seconds])
        unknown = sum(record.result == "unknown" for record in records)
        result.append(dict(key="profiles", kind="profiles", chat_id=None, grade=None,
                           window=profiles.window_seconds, samples=len(records), matches=unknown,
                           minimum=profiles.minimum_users, minimum_matches=profiles.minimum_matches,
                           value=100 * unknown / len(records) if records else 0,
                           threshold=profiles.threshold_percent, enabled=len(records) >= profiles.minimum_users,
                           missing=f"{len(records)}/{profiles.minimum_users}"))
        today = self.day(now)
        days = [today - timedelta(days=index) for index in range(1, self.config.candidate_history_days + 1)]
        complete = []
        for day in days:
            record = self.state.days.get(day.isoformat())
            start, end = self._day_bounds(day)
            if record and record.coverage_seconds + 0.001 >= (end - start) * self.config.minimum_day_coverage_percent / 100:
                complete.append(record)
        current = self.state.days.get(today.isoformat(), DayObservation())
        for grade in ("G1", "G2", "G3", "G4"):
            values = [sum(value == grade for value in record.candidates.values()) for record in complete]
            mean = sum(values) / len(values) if values else 0
            threshold = max(self.config.candidate_minimum_users[grade],
                            math.ceil(self.config.candidate_coefficients[grade] * mean))
            count = sum(value == grade for value in current.candidates.values())
            result.append(dict(key="candidates:" + grade, kind="candidates", grade=grade, chat_id=None,
                               window=86400, samples=len(complete), matches=count,
                               minimum=self.config.candidate_history_days, minimum_matches=threshold,
                               value=count, threshold=threshold,
                               enabled=len(complete) == len(days), missing=f"{len(complete)}/{len(days)}",
                               baseline=values, coefficient=self.config.candidate_coefficients[grade],
                               quarantine=sum(candidate.grade == grade for candidate in self.state.quarantine.values())))
        return result

    def evaluate(self, now=None):
        now = time.time() if now is None else now
        active = []
        for metric in self.measurements(now):
            if (metric["enabled"] and metric["matches"] >= metric["minimum_matches"]
                    and metric["value"] >= metric["threshold"]):
                active.append(metric["key"])
                signal = SafetySignal(key=metric["key"], kind=metric["kind"], at=now,
                                      value=metric["value"], threshold=metric["threshold"],
                                      chat_id=metric["chat_id"], grade=metric["grade"])
                if signal.key not in self.state.active_rule_keys and signal.key in self.state.reasons:
                    # A fresh burst invalidates approvals from a previous burst of the same rule.
                    self.state.reasons.pop(signal.key)
                if signal.key not in self.state.active_rule_keys:
                    self._sample(metric["key"], metric["value"], now, metric["window"],
                                 samples=metric["samples"], matches=metric["matches"],
                                 percentage=metric["kind"] != "candidates", force=True,
                                 attempts=metric.get("attempts", 0), false_attempts=metric.get("false_attempts", 0))
                self.trip(signal)
        if set(active) != set(self.state.active_rule_keys):
            self.state.active_rule_keys = active
            self.changed()

    def tick(self, now=None):
        now = time.time() if now is None else now
        self.collect(now)
        self.prune(now)
        self.evaluate(now)
        if self.service.state.status == "running":
            for metric in self.measurements(now):
                self._sample(metric["key"], metric["value"], now, metric["window"],
                             samples=metric["samples"], matches=metric["matches"],
                             percentage=metric["kind"] != "candidates", attempts=metric.get("attempts", 0),
                             false_attempts=metric.get("false_attempts", 0))
            self._sample("quarantine", len(self.state.quarantine), now, 0)
            activity = len({user for at, user in self.state.activity_conflicts
                            if at > now - self.config.activity_window_seconds})
            self._sample("activity", activity, now, self.config.activity_window_seconds)
            for limit in self.config.removal_limits:
                entries = [entry for entry in self.state.reservations if (entry.at > now - limit.window_seconds or entry.state == "pending")
                           and entry.state != "released" and (not entry.dry_run or self.service.config.dry_run)]
                self._sample("budget:" + limit.name, len(entries), now, limit.window_seconds)

    def _sample(self, key, value, now, window, *, samples=None, matches=None, percentage=False,
                attempts=0, false_attempts=0, force=False):
        history = self.state.metrics.setdefault(key, [])
        if not force and history and now - history[-1].at < self.config.metric_sample_seconds:
            return
        samples = int(value) if samples is None else samples
        matches = int(value) if matches is None else matches
        if not history or self.day(history[-1].at) != self.day(now) or history[-1].window_seconds != window:
            history.append(MetricObservation(at=now, samples=samples, matches=matches, value=value,
                                             window_seconds=window, percentage=percentage))
        history[-1].observe(samples, matches, value, now, attempts, false_attempts)
        self.changed()

    def metric_history(self, key, now=None, window=None):
        now = time.time() if now is None else now
        today = self.day(now)
        cutoff = today - timedelta(days=self.config.metric_history_days - 1)
        return [entry for entry in self.state.metrics.get(key, []) if cutoff <= self.day(entry.at) <= today
                and (window is None or entry.window_seconds == window)]

    def prune(self, now):
        def size():
            return (len(self.state.checks), len(self.state.activity_conflicts),
                    len(self.state.cancelled_candidates), len(self.state.rejected_until), len(self.state.days),
                    len(self.state.reservations), len(self.state.requests),
                    sum(len(entries) for entries in self.state.metrics.values()))

        before = size()
        checks_horizon = max(self.config.false_results.window_seconds, self.config.alive_transitions.window_seconds,
                             self.config.profile_inconsistencies.window_seconds)
        self.state.checks = [entry for entry in self.state.checks if entry.at > now - checks_horizon]
        self.state.activity_conflicts = [entry for entry in self.state.activity_conflicts
                                         if entry[0] > now - self.config.activity_window_seconds]
        self.state.cancelled_candidates = [entry for entry in self.state.cancelled_candidates
                                           if entry[0] > now - self.config.metric_history_days * 86400]
        self.state.rejected_until = {user: until for user, until in self.state.rejected_until.items() if until > now}
        history_cutoff = self.day(now) - timedelta(days=self.config.metric_history_days)
        self.state.metrics = {key: [entry for entry in entries if self.day(entry.at) >= history_cutoff]
                              for key, entries in self.state.metrics.items()}
        day_cutoff = self.day(now) - timedelta(days=self.config.candidate_history_days + 1)
        self.state.days = {key: value for key, value in self.state.days.items() if key >= day_cutoff.isoformat()}
        reservation_horizon = max(max(item.window_seconds for item in self.config.removal_limits),
                                  self.config.removal_statistics_days * 86400,
                                  self.config.reservation_retention_days * 86400)
        discarded = [entry.at for entry in self.state.reservations
                     if entry.at <= now - reservation_horizon and entry.state != "pending"]
        if discarded:
            self.state.reservations_discarded_until = max(self.state.reservations_discarded_until, max(discarded))
        self.state.reservations = [entry for entry in self.state.reservations
                                   if entry.at > now - reservation_horizon or entry.state == "pending"]
        self.state.requests = {key: request for key, request in self.state.requests.items()
                               if request.state == "pending" or key == self.state.current_request_id
                               or (request.decided_at or request.created_at) > now - self.config.resolved_request_retention_days * 86400}
        for candidate in list(self.state.quarantine.values()):
            for chat_id, generation in list(candidate.targets.items()):
                row = self.service.state.participants.get(chat_id, {}).get(candidate.user_id)
                if (not self.service.bot_state.is_chat_moderated(chat_id) or row is None
                        or not row.active or row.generation != generation):
                    self.finish_target(candidate.user_id, chat_id)
        if before != size():
            self.changed()

    async def populations(self):
        now = time.time()
        chats = sorted(set(self.service.bot_state.moderated_chat_ids))
        if (self.state.populations_chats == chats
                and now - self.state.populations_at < self.config.member_count_cache_seconds):
            return dict(self.state.populations)
        populations = {}
        for chat_id in chats:
            count = await self.service.api.call(self.service.bot.get_chat_member_count,
                                                chat_id=chat_id, error_chat_id=chat_id)
            if type(count) is not int or count <= 0:
                raise ValueError("Telegram returned an invalid member count")
            populations[chat_id] = count
        if chats != sorted(set(self.service.bot_state.moderated_chat_ids)):
            raise ValueError("Moderated chats changed while member counts were collected")
        self.state.populations, self.state.populations_at = populations, now
        self.state.populations_chats = chats
        self.changed()
        return dict(populations)

    def budget_failure(self, chat_id, populations, now=None, *, reservation=None):
        now = time.time() if now is None else now
        if chat_id not in populations or any(value <= 0 for value in populations.values()):
            return SafetySignal(key="population-unavailable", kind="population", at=now)
        for limit in self.config.removal_limits:
            if now - limit.window_seconds < self.state.reservations_discarded_until:
                return SafetySignal(key="budget-history-unavailable", kind="budget_history", at=now,
                                    value=limit.window_seconds)
            if self.limits_bypassed(now):
                continue
            entries = [entry for entry in self.state.reservations
                       if (entry.at > now - limit.window_seconds or entry.state == "pending") and entry.state != "released"
                       and (not entry.dry_run or self.service.config.dry_run)]
            local = [entry for entry in entries if entry.chat_id == chat_id]
            chat_base = min([populations[chat_id]] + [entry.chat_population for entry in local if entry.chat_population > 0])
            global_base = min([sum(populations.values())] + [entry.global_population for entry in entries if entry.global_population > 0])
            for scope, records, base, percent in (
                    (chat_id, local, chat_base, limit.chat_percent),
                    (None, entries, global_base, limit.global_percent)):
                count = len(records) + (0 if reservation is not None and any(
                    entry.id == reservation.id for entry in records
                ) else 1)
                allowed = math.floor(base * percent / 100)
                if count > allowed:
                    return SafetySignal(key=f"quota:{limit.name}:{scope}", kind="quota", at=now,
                                        value=100 * count / base, threshold=percent, chat_id=scope, unit="percent")
        return None

    async def reserve(self, job, guard):
        try:
            populations = await self.populations()
        except CoronerInterrupted:
            raise
        except Exception:
            self.trip(SafetySignal(key="population-unavailable", kind="population", at=time.time()))
            await self.service.save(force=True)
            return None
        guard()
        failure = self.budget_failure(job.chat_id, populations)
        if failure is not None:
            self.trip(failure)
            await self.service.save(force=True)
            return None
        reservation = RemovalReservation(user_id=job.user_id, chat_id=job.chat_id, at=time.time(),
                                         chat_population=populations[job.chat_id],
                                         global_population=sum(populations.values()), dry_run=self.service.config.dry_run)
        self.state.reservations.append(reservation)
        self.changed()
        if not await self.service.save(force=True):
            return None
        return reservation

    def schedule_notifications(self):
        application = self.service.application
        if application is None or not application.running or not self.is_blocked():
            return
        if self._notification_task is not None and not self._notification_task.done():
            return
        now = time.time()
        if now < self._notification_retry_at:
            return
        request = self.state.requests.get(self.state.current_request_id)
        if request is None:
            request = self.new_request(now)
        if request.notification_at and now - request.notification_at < self.config.notification_interval_seconds:
            return
        self._notification_retry_at = now + self.config.notification_interval_seconds
        self._notification_task = application.create_task(self.notify(request.id))

    async def notify(self, request_id):
        from src.coroner.CoronerProtectionView import CoronerProtectionView
        from src.util.data.BotEvent import BotEvent

        request = self.state.requests.get(request_id)
        if request is None:
            return
        view = CoronerProtectionView(self.service, self.service.locale)
        for subscriber in self.service.bot_state.get_event_subscribers(BotEvent.SERVICE):
            try:
                if not await self.service.authorized(subscriber, subscriber):
                    continue
                # A new anomaly may supersede the snapshot while authorization is awaited.
                if self.state.current_request_id != request_id:
                    return
                message_id = request.notifications.get(subscriber)
                message = await view.display("review", request_id, 0, subscriber, message_id=message_id)
                if message_id is None and message is not None:
                    request.notifications[subscriber] = message.message_id
                self.changed()
                await self.service.save()
            except CoronerInterrupted:
                return
            except TelegramError:
                pass  # The common API wrapper recorded the notification error.
            except Exception as error:
                self.service._error(None, "protection-notification", "worker_error", detail=error)
        request.notification_at = time.time()
        self.changed()
        await self.service.save()
