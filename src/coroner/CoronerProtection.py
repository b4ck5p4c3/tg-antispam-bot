import json
import math
import time
from datetime import datetime, timedelta

from telegram.error import TelegramError

from src.coroner.CoronerApi import CoronerInterrupted
from src.coroner.CoronerMessages import duration
from src.coroner.CoronerProtectionModels import (
    AnomalyApproval, CheckObservation, DayObservation, MetricObservation,
    QuarantineCandidate, RemovalReservation, SafetySignal,
    calendar_timezone,
)


class CoronerProtection:
    """Persistent quarantine and safety decisions. Telegram mutations stay in the service."""

    REVIEWABLE_KINDS = frozenset((
        "false", "candidates", "transitions", "profiles", "activity", "interrupted", "manual",
        "population", "budget_history",
    ))

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
        # Old quota incidents used absolute counts; enforce the current percentages
        # again before the next removal instead of retaining obsolete count caps.
        retired = [key for key, signal in self.state.reasons.items()
                   if key == "api" or (signal.kind == "quota" and signal.unit is None)]
        for key in retired:
            del self.state.reasons[key]
            self.state.approvals.pop(key, None)
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
        self.evaluate(now)
        # Persist schema migration, including removal of old account review snapshots.
        self.changed()

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
                                   user_id=user_id,
                                   rule=json.dumps([self.config.activity_window_seconds, self.config.activity_minimum_users])),
                      new_incident=True)
        user = self.service.state.users.get(user_id)
        if user is not None:
            user.last_alive_at = now
        self.changed()

    def enter(self, job, user, now=None):
        now = time.time() if now is None else now
        if self.state.rejected_until.get(job.user_id, 0) > now:
            return None
        candidate = self.state.quarantine.get(job.user_id)
        if candidate is None:
            candidate = QuarantineCandidate(
                user_id=job.user_id, grade=self.service._user_grade(job.user_id, now).name,
                detected_at=now, ready_at=now + self.config.quarantine_seconds,
                targets=list(user.chat_ids), generation=user.generation,
            )
            self.state.quarantine[job.user_id] = candidate
            day = self.state.days.setdefault(self.day(now).isoformat(), DayObservation())
            day.candidates.setdefault(job.user_id, candidate.grade)
        self.changed()
        self.evaluate(now)
        return candidate

    def permitted(self, candidate, chat_id, generation, now=None):
        now = time.time() if now is None else now
        if (self.state.quarantine.get(candidate.user_id) is not candidate
                or chat_id not in candidate.targets or candidate.generation != generation or now < candidate.ready_at):
            return False
        return not self.is_blocked(now)

    def limits_bypassed(self, now=None):
        now = time.time() if now is None else now
        return now < self.state.removal_limit_bypass_until

    def blocking_reasons(self, now=None):
        return [signal for signal in self.state.reasons.values()
                if (not self.limits_bypassed(now) if signal.kind == "quota" else not self.is_approved(signal))]

    def is_approved(self, signal):
        approval = self.state.approvals.get(signal.key)
        return signal.kind in self.REVIEWABLE_KINDS and approval is not None and approval.rule == signal.rule

    def approval_status(self, t):
        count = sum(self.is_approved(signal) for signal in self.state.reasons.values())
        return t("review_permissions", count=count)

    def is_blocked(self, now=None):
        return bool(self.blocking_reasons(now))

    def _wake_quarantine(self):
        for candidate in self.state.quarantine.values():
            user = self.service.state.users.get(candidate.user_id)
            if (user is None or candidate.generation != user.generation or not candidate.targets
                    or not self.permitted(candidate, candidate.targets[0], user.generation)):
                continue
            self.service._enqueue(candidate.user_id, "manual")
            job = self.service.state.queue.get(str(candidate.user_id))
            if job is not None and not job.attempts:
                job.not_before = 0
                self.changed()

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
            self._wake_quarantine()
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
        if chat_id in candidate.targets:
            candidate.targets.remove(chat_id)
        if not candidate.targets:
            self.state.quarantine.pop(user_id, None)
        self.changed()

    def trip(self, signal, *, new_incident=False):
        previous = self.state.reasons.get(signal.key)
        if previous is not None and previous.rule == signal.rule and not new_incident:
            if previous != signal.model_copy(update={"at": previous.at}):
                signal.at = previous.at
                self.state.reasons[signal.key] = signal
                self.changed()
            return
        self.state.approvals.pop(signal.key, None)
        self.state.reasons.pop(signal.key, None)
        self.state.reasons[signal.key] = signal
        self.state.notification_version += 1
        self.state.notification_at = 0
        self._notification_retry_at = 0
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

    async def approve_anomalies(self, user_id):
        if not self.service._storage_healthy or not self.service._config_healthy:
            return "review_failed"
        now = time.time()
        self.evaluate(now)
        previous = dict(self.state.approvals)
        for signal in self.state.reasons.values():
            if signal.kind in self.REVIEWABLE_KINDS and not self.is_approved(signal):
                self.state.approvals[signal.key] = AnomalyApproval(user_id=user_id, at=now, rule=signal.rule)
        if previous == self.state.approvals:
            return "review_no_anomalies"
        self.state.notification_version += 1
        self._wake_quarantine()
        self.changed()
        if not await self.service.save(force=True):
            self.state.approvals = previous
            self.changed()
            return "review_failed"
        self.service.logger.warning("CORONER anomalies approved by=%s rules=%s", user_id, list(self.state.approvals))
        return "review_decided"

    def acknowledge(self):
        self.evaluate()
        if self.state.quarantine or any(signal.kind in (
                "false", "transitions", "profiles", "candidates", "activity") for signal in self.state.reasons.values()):
            return "review_cannot_resume"
        self.state.reasons.clear()
        self.state.approvals.clear()
        self.state.notification_version += 1
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
        was_blocked = self.is_blocked(now)
        active = set()
        for metric in self.measurements(now):
            if (metric["enabled"] and metric["matches"] >= metric["minimum_matches"]
                    and metric["value"] >= metric["threshold"]):
                active.add(metric["key"])
                rule = json.dumps([metric["window"], metric["threshold"], metric["minimum"],
                                   metric["minimum_matches"],
                                   self.day(now).isoformat() if metric["kind"] == "candidates" else None])
                signal = SafetySignal(key=metric["key"], kind=metric["kind"], at=now,
                                      value=metric["value"], threshold=metric["threshold"],
                                      chat_id=metric["chat_id"], grade=metric["grade"], rule=rule)
                if signal.key not in self.state.reasons:
                    self._sample(metric["key"], metric["value"], now, metric["window"],
                                 samples=metric["samples"], matches=metric["matches"],
                                 percentage=metric["kind"] != "candidates", force=True,
                                 attempts=metric.get("attempts", 0), false_attempts=metric.get("false_attempts", 0))
                self.trip(signal)
        activity = len({user for at, user in self.state.activity_conflicts
                        if at > now - self.config.activity_window_seconds})
        if activity >= self.config.activity_minimum_users:
            active.add("candidate-activity")
            previous = self.state.reasons.get("candidate-activity")
            self.trip(SafetySignal(key="candidate-activity", kind="activity", at=now,
                                   value=activity, threshold=self.config.activity_minimum_users,
                                   user_id=previous.user_id if previous else None,
                                   rule=json.dumps([self.config.activity_window_seconds, self.config.activity_minimum_users])))
        for key, signal in list(self.state.reasons.items()):
            if signal.kind in ("false", "transitions", "profiles", "candidates", "activity") and key not in active:
                self._resolve(key)
        if (self.state.populations_chats == sorted(set(self.service.bot_state.moderated_chat_ids))
                and self.state.populations and all(value > 0 for value in self.state.populations.values())
                and now - self.state.populations_at < self.config.member_count_cache_seconds):
            self._resolve("population-unavailable")
        horizon = max(limit.window_seconds for limit in self.config.removal_limits)
        if now - horizon >= self.state.reservations_discarded_until:
            self._resolve("budget-history-unavailable")
        if not any(entry.state == "uncertain" and entry.at > now - horizon for entry in self.state.reservations):
            self._resolve("uncertain-removal")
            self._resolve("interrupted-removal")
        for key in set(self.state.approvals) - self.state.reasons.keys():
            del self.state.approvals[key]
            self.changed()
        self._refresh_quota_reasons(now)
        if was_blocked and not self.is_blocked(now):
            self._wake_quarantine()

    def _resolve(self, key):
        if self.state.reasons.pop(key, None) is not None:
            self.state.approvals.pop(key, None)
            self.state.notification_version += 1
            self.service.logger.info("CORONER protection condition normalized: %s", key)
            self.changed()

    def _refresh_quota_reasons(self, now):
        limits = {limit.name: limit for limit in self.config.removal_limits}
        chats = set(self.service.bot_state.moderated_chat_ids)
        populations = self.state.populations
        for key, signal in list(self.state.reasons.items()):
            if signal.kind != "quota":
                continue
            limit = limits.get(key.split(":")[1]) if key.startswith("quota:") else None
            if limit is None or (signal.chat_id is not None and signal.chat_id not in chats):
                self._resolve(key)
                continue
            # Fresh counts are fetched again by reserve before any actual removal.
            if set(populations) != chats or not populations or any(value <= 0 for value in populations.values()):
                continue
            chat_id = signal.chat_id if signal.chat_id is not None else next(iter(chats))
            for scope, count, base, percent in self._budget_usage(limit, chat_id, populations, now):
                if scope != signal.chat_id:
                    continue
                if count <= math.floor(base * percent / 100):
                    self._resolve(key)
                elif signal.value != 100 * count / base or signal.threshold != percent:
                    signal.value, signal.threshold = 100 * count / base, percent
                    self.changed()
                break

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
                    len(self.state.reservations),
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
        for candidate in list(self.state.quarantine.values()):
            user = self.service.state.users.get(candidate.user_id)
            for chat_id in list(candidate.targets):
                if (user is None or candidate.generation != user.generation or chat_id not in user.chat_ids
                        or not self.service.bot_state.is_chat_moderated(chat_id)):
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
            for scope, count, base, percent in self._budget_usage(limit, chat_id, populations, now, reservation):
                allowed = math.floor(base * percent / 100)
                if count > allowed:
                    return SafetySignal(key=f"quota:{limit.name}:{scope}", kind="quota", at=now,
                                        value=100 * count / base, threshold=percent, chat_id=scope, unit="percent")
        return None

    def _budget_usage(self, limit, chat_id, populations, now, reservation=None):
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
            yield scope, count, base, percent

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
        if self.state.notification_at and now - self.state.notification_at < self.config.notification_interval_seconds:
            return
        self._notification_retry_at = now + self.config.notification_interval_seconds
        self._notification_task = application.create_task(self.notify(self.state.notification_version))

    async def notify(self, version):
        from src.coroner.CoronerProtectionView import CoronerProtectionView
        from src.util.data.BotEvent import BotEvent

        view = CoronerProtectionView(self.service, self.service.locale)
        for subscriber in self.service.bot_state.get_event_subscribers(BotEvent.SERVICE):
            try:
                if not await self.service.authorized(subscriber, subscriber):
                    continue
                if self.state.notification_version != version or not self.is_blocked():
                    return
                message_id = self.state.notifications.get(subscriber)
                message = await view.display("review", 0, subscriber, message_id=message_id)
                if message_id is None and message is not None:
                    self.state.notifications[subscriber] = message.message_id
                self.changed()
                await self.service.save()
            except CoronerInterrupted:
                return
            except TelegramError:
                pass  # The common API wrapper recorded the notification error.
            except Exception as error:
                self.service._error(None, "protection-notification", "worker_error", detail=error)
        if self.state.notification_version == version:
            self.state.notification_at = time.time()
            self.changed()
            await self.service.save()
