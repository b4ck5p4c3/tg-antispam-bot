import math
import time
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.coroner.CoronerMessages import coroner_text, duration, shorten
from src.coroner.CoronerProtectionModels import MetricObservation
from src.telegram.KeyboardData import KeyboardData


class CoronerProtectionKeyboardData(KeyboardData):
    key_id: str = "CORONER_UI"
    action: str
    request_id: str = "-"
    page: int = 0
    user_id: int = 0


class CoronerProtectionView:
    def __init__(self, service, locale):
        self.service = service
        self.protection = service.protection
        self.locale = locale

    def t(self, key, **values):
        return coroner_text(self.locale, key, **values)

    def button(self, key, action, request_id="-", page=0, user_id=0):
        data = CoronerProtectionKeyboardData(action=action, request_id=request_id, page=page, user_id=user_id)
        return InlineKeyboardButton(self.t(key), callback_data=data.model_dump())

    def main_buttons(self):
        return [[self.button("detectors", "detectors"), self.button("quarantine_button", "quarantine")],
                [self.button("reviews", "review")]]

    def _profile_link(self, user_id):
        return (f'<a href="tg://user?id={user_id}">'
                f'{escape(self.t("candidate_profile"))} · {user_id}</a>')

    def _navigation(self, action, request_id, page, pages):
        buttons = []
        if page:
            buttons.append(self.button("previous", action, request_id, page - 1))
        if page + 1 < pages:
            buttons.append(self.button("next", action, request_id, page + 1))
        return [buttons] if buttons else []

    @staticmethod
    def _stats(values):
        if not values:
            return "— / — / —"
        return f"{min(values):.2f} / {max(values):.2f} / {sum(values) / len(values):.2f}"

    @staticmethod
    def _history_stats(entries, field="value_range"):
        records = [getattr(entry, field) for entry in entries if getattr(entry, field).count]
        if not records:
            return "— / — / —"
        minimum = min(record.minimum for record in records)
        maximum = max(record.maximum for record in records)
        mean = sum(record.total for record in records) / sum(record.count for record in records)
        return f"{minimum:.2f} / {maximum:.2f} / {mean:.2f}"

    def _history_with_current(self, key, value, now, window=0, *, samples=None, matches=None,
                               percentage=False, attempts=0, false_attempts=0):
        samples = int(value) if samples is None else samples
        matches = int(value) if matches is None else matches
        current = MetricObservation(at=now, samples=samples, matches=matches, value=value,
                                    window_seconds=window, percentage=percentage)
        current.observe(samples, matches, value, now, attempts, false_attempts)
        return self.protection.metric_history(key, now, window) + [current]

    def _detectors(self, page):
        now = time.time()
        metrics = self.protection.measurements(now)
        cards = []
        for metric in metrics:
            scope = str(metric["chat_id"]) if metric["chat_id"] is not None else (metric["grade"] or "ALL")
            lines = [self.t("detector_title", kind=self.t("safety_kind_" + metric["kind"]), scope=scope,
                            period=duration(metric["window"]))]
            lines.append(self.t("detector_enabled") if metric["enabled"] else self.t(
                "detector_disabled", available=metric["missing"],
            ))
            progress = 100 * metric["value"] / metric["threshold"] if metric["threshold"] else 0
            lines.append(self.t("detector_current", samples=metric["samples"], matches=metric["matches"],
                               value=f"{metric['value']:.2f}", threshold=f"{metric['threshold']:.2f}",
                               progress=f"{progress:.2f}", unit="" if metric["kind"] == "candidates" else "%"))
            lines.append(self.t("detector_minimum", samples=metric["minimum"], matches=metric["minimum_matches"]))
            if metric["kind"] == "candidates":
                lines.append(self.t("detector_candidates", count=metric["quarantine"],
                                   coefficient=metric["coefficient"],
                                   history=self._stats(metric["baseline"])))
            else:
                history = self._history_with_current(metric["key"], metric["value"], now, metric["window"],
                                                     samples=metric["samples"], matches=metric["matches"],
                                                     percentage=True, attempts=metric.get("attempts", 0),
                                                     false_attempts=metric.get("false_attempts", 0))
                weighted_samples = sum(entry.weighted_samples for entry in history)
                lines.extend([
                    self.t("detector_history", days=self.protection.config.metric_history_days,
                           samples=self._history_stats(history, "sample_range"),
                           matches=self._history_stats(history, "match_range"),
                           values=self._history_stats(history)),
                    self.t("detector_weighted", value=(
                        f"{100 * sum(entry.weighted_matches for entry in history) / weighted_samples:.2f}%"
                        if weighted_samples else "—")),
                ])
                if metric["kind"] == "false":
                    lines.append(self.t("detector_checks", count=metric["attempts"],
                                        deleted=metric["false_attempts"], unknown=metric["unknown_attempts"],
                                        checks_history=self._history_stats(history, "attempts_range"),
                                        deleted_history=self._history_stats(history, "false_attempts_range")))
            cards.append("\n".join(lines))
        cfg, state = self.protection.config, self.protection.state
        ready = sum(now >= item.ready_at for item in state.quarantine.values())
        oldest = max((now - item.detected_at for item in state.quarantine.values()), default=0)
        q_history = self._history_with_current("quarantine", len(state.quarantine), now)
        cards.append(self.t("quarantine_summary", count=len(state.quarantine), ready=ready,
                            oldest=duration(oldest), delay=duration(cfg.quarantine_seconds),
                            history=self._history_stats(q_history),
                            cancelled=len(state.cancelled_candidates)))
        conflicts = len({user for at, user in state.activity_conflicts if at > now - cfg.activity_window_seconds})
        cards.append(self.t("activity_settings", count=conflicts, minimum=cfg.activity_minimum_users,
                            period=duration(cfg.activity_window_seconds), recent=duration(cfg.recent_alive_seconds),
                            approval=duration(cfg.approval_seconds), cooldown=duration(cfg.rejection_cooldown_seconds),
                            sampling=duration(cfg.metric_sample_seconds), timezone=cfg.day_timezone,
                            coverage=cfg.minimum_day_coverage_percent) + "\n" + self.t(
                                "count_history", history=self._history_stats(self._history_with_current(
                                    "activity", conflicts, now, cfg.activity_window_seconds))))
        for limit in cfg.removal_limits:
            entries = [item for item in state.reservations if (item.at > now - limit.window_seconds or item.state == "pending")
                       and item.state != "released" and (not item.dry_run or self.service.config.dry_run)]
            counts = {}
            for item in entries:
                counts[item.chat_id] = counts.get(item.chat_id, 0) + 1
            cards.append(self.t("limit_summary", name=limit.name, period=duration(limit.window_seconds),
                                count=len(entries), maximum=limit.global_count, percent=limit.global_percent,
                                local=limit.chat_count, local_percent=limit.chat_percent,
                                chats=shorten(str(counts), 300)) + "\n" + self.t("count_history", history=self._history_stats(
                                    self._history_with_current("budget:" + limit.name, len(entries), now,
                                                               limit.window_seconds))))
        population = sum(state.populations.values()) if state.populations_chats == sorted(set(
            self.service.bot_state.moderated_chat_ids)) and now - state.populations_at < cfg.member_count_cache_seconds else 0
        removed_lines = [self.t("removed_period", days=cfg.removal_statistics_days)]
        for grade in ("G1", "G2", "G3", "G4"):
            rows = [entry for entry in self.service.state.removals
                    if entry.removed_at > now - cfg.removal_statistics_days * 86400 and entry.grade == grade]
            percent = f"{100 * len(rows) / population:.2f}%" if population else self.t("unavailable")
            removed_lines.append(self.t("removed_grade", grade=grade, users=len({entry.user_id for entry in rows}),
                                        count=len(rows), percent=percent))
        cards.append("\n".join(removed_lines))
        pages = max(1, math.ceil(len(cards) / cfg.detector_page_size))
        page = max(0, min(page, pages - 1))
        text = self.t("detector_heading") + "\n" + self.t("protection_status", status=self.t(
            "protection_blocked" if state.blocked else "protection_clear")) + "\n"
        text += self.t("page", page=page + 1, pages=pages) + "\n\n"
        text += "\n\n".join(cards[page * cfg.detector_page_size:(page + 1) * cfg.detector_page_size])
        buttons = self._navigation("detectors", "-", page, pages)
        buttons += [[self.button("update", "detectors", page=page), self.button("back", "status")]]
        return shorten(text, 4000), InlineKeyboardMarkup(buttons), None

    def _review(self, request_id, actor_id, page=0):
        state = self.protection.state
        request = state.requests.get(request_id)
        lines = [self.t("review_heading"), self.t("protection_status", status=self.t(
            "protection_blocked" if state.blocked else "protection_clear",
        ))]
        for signal in list(state.reasons.values())[-8:]:
            lines.append(self.protection.reason_text(signal))
        buttons = []
        if request is None:
            lines.append(self.t("review_none"))
        else:
            lines.extend([
                self.t("review_identity", request_id=request.id, status=request.state,
                       age=duration(time.time() - request.created_at)),
                self.t("review_counts", users=len(request.targets),
                       targets=sum(len(target.targets) for target in request.targets.values()),
                       current=len(state.quarantine), selected=len(request.selections.get(actor_id, []))),
                self.t("review_approval_lifetime", duration=duration(self.protection.config.approval_seconds)),
            ])
            grades = dict.fromkeys(("G1", "G2", "G3", "G4"), 0)
            chats = {}
            for user, snapshot in request.targets.items():
                candidate = state.quarantine.get(user)
                grade = snapshot.grade or (candidate.grade if candidate else None)
                if grade in grades:
                    grades[grade] += 1
                for chat_id in snapshot.targets:
                    chats[chat_id] = chats.get(chat_id, 0) + 1
            lines.append(", ".join(f"{grade}: {count}" for grade, count in grades.items()))
            size = self.protection.config.review_page_size
            pages = max(1, math.ceil(len(chats) / size))
            page = max(0, min(page, pages - 1))
            lines.append(self.t("review_chat_distribution"))
            lines.extend(f"{chat_id}: {count}" for chat_id, count in sorted(chats.items())[page * size:(page + 1) * size])
            lines.append(self.t("page", page=page + 1, pages=pages))
            buttons.extend(self._navigation("review", request_id, page, pages))
            buttons.append([self.button("review_accounts", "accounts", request.id)])
            if request.state == "pending" and request.epoch == state.epoch:
                buttons.extend([
                    [self.button("approve_selected", "approve", request.id),
                     self.button("approve_all", "approve_all", request.id)],
                    [self.button("reject_all", "reject", request.id), self.button("recheck", "recheck", request.id)],
                ])
        buttons.extend([
            [self.button("review_new" if state.blocked else "pause_review", "new"),
             self.button("review_resume", "ack")],
            [self.button("update", "review", request_id), self.button("back", "status")],
        ])
        return shorten("\n".join(lines), 4000), InlineKeyboardMarkup(buttons), None

    def _accounts(self, request_id, actor_id, page, *, quarantine=False):
        state = self.protection.state
        request = state.requests.get(request_id)
        ids = sorted(state.quarantine) if quarantine else sorted(request.targets) if request else []
        size = self.protection.config.review_page_size
        pages = max(1, math.ceil(len(ids) / size))
        page = max(0, min(page, pages - 1))
        heading = (self.t("quarantine_count", count=len(ids)) if quarantine else
                   f'{self.t("review_accounts")}: {len(ids)}')
        lines = [escape(heading),
                 self.t("page", page=page + 1, pages=pages)]
        buttons = []
        for user in ids[page * size:(page + 1) * size]:
            candidate = state.quarantine.get(user)
            if not quarantine and candidate is not None and request.targets[user].candidate_id != candidate.id:
                candidate = None
            selected = request is not None and user in request.selections.get(actor_id, [])
            lines.append(self._profile_link(user) + "\n" + escape(
                self.t("candidate_line", grade=self.service._user_grade(user, time.time()).name,
                       detected_grade=candidate.grade, age=duration(time.time() - candidate.detected_at),
                       remaining=duration(candidate.ready_at - time.time()), targets=len(candidate.targets))
                if candidate is not None else self.t("candidate_gone")))
            if (request is not None and user in request.targets and request.state == "pending"
                    and request.epoch == state.epoch
                    and candidate is not None and request.targets[user].candidate_id == candidate.id):
                buttons.append([InlineKeyboardButton(
                    f'{self.t("selected" if selected else "select")} {user}',
                    callback_data=CoronerProtectionKeyboardData(
                        action="qselect" if quarantine else "select",
                        request_id=request_id, page=page, user_id=user,
                    ).model_dump(),
                )])
        if not ids:
            lines.append(escape(self.t("no_candidates")))
        action = "quarantine" if quarantine else "accounts"
        buttons += self._navigation(action, request_id, page, pages)
        buttons += [[self.button("update", action, request_id, page), self.button("reviews", "review", request_id)],
                    [self.button("back", "status")]]
        return "\n\n".join(lines), InlineKeyboardMarkup(buttons), "HTML"

    def _detail(self, request_id, actor_id, page, user_id):
        candidate = self.protection.state.quarantine.get(user_id)
        request = self.protection.state.requests.get(request_id)
        if (request is not None and user_id in request.targets and candidate is not None
                and request.targets[user_id].candidate_id != candidate.id):
            candidate = None
        lines = [self._profile_link(user_id)]
        if candidate is None:
            lines.append(escape(self.t("candidate_gone")))
        else:
            lines.append(escape(self.t("candidate_line", grade=self.service._user_grade(user_id, time.time()).name,
                                       detected_grade=candidate.grade,
                                       age=duration(time.time() - candidate.detected_at),
                                       remaining=duration(candidate.ready_at - time.time()), targets=len(candidate.targets))))
            targets = sorted(candidate.targets)
            size = self.protection.config.review_page_size
            target_pages = max(1, math.ceil(len(targets) / size))
            detail_page = max(0, min(page, target_pages - 1))
            lines.append(escape(self.t("candidate_targets")))
            lines.extend(str(chat) for chat in targets[detail_page * size:(detail_page + 1) * size])
            lines.append(self.t("page", page=detail_page + 1, pages=target_pages))
        buttons = []
        if candidate is not None:
            nav = []
            if detail_page:
                nav.append(self.button("previous", "detail", request_id, detail_page - 1, user_id))
            if detail_page + 1 < target_pages:
                nav.append(self.button("next", "detail", request_id, detail_page + 1, user_id))
            if nav:
                buttons.append(nav)
        if request is not None and user_id in request.targets and request.state == "pending" and candidate is not None:
            selected = user_id in request.selections.get(actor_id, [])
            buttons.append([self.button("selected" if selected else "select", "select", request_id, 0, user_id)])
        buttons += [[self.button("back", "accounts" if request else "quarantine", request_id)]]
        return "\n\n".join(lines), InlineKeyboardMarkup(buttons), "HTML"

    def render(self, action, request_id, actor_id, page, user_id):
        if request_id == "-":
            request_id = self.protection.state.current_request_id or "-"
        if action == "detectors":
            return self._detectors(page)
        if action in ("accounts", "quarantine"):
            return self._accounts(request_id, actor_id, page, quarantine=action == "quarantine")
        if action == "detail":
            return self._detail(request_id, actor_id, page, user_id)
        return self._review(request_id, actor_id, page)
