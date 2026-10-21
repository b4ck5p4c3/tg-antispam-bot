import math
import time

from pydantic import model_validator

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.coroner.CoronerMessages import coroner_text, duration, shorten
from src.coroner.CoronerProtectionModels import MetricObservation
from src.telegram.KeyboardData import KeyboardData


class CoronerProtectionKeyboardData(KeyboardData):
    key_id: str = "CORONER_UI"
    action: str
    page: int = 0

    @model_validator(mode="before")
    @classmethod
    def parse_from_string(cls, value):
        # Keep navigation and confirmation in already-sent review messages working.
        if isinstance(value, str):
            parts = value.split(cls.SEP)
            if len(parts) in (4, 5):
                value = cls.SEP.join([parts[0], parts[1], parts[3]])
        return super().parse_from_string(value)


class CoronerProtectionView:
    def __init__(self, service, locale):
        self.service = service
        self.protection = service.protection
        self.locale = locale

    def t(self, key, **values):
        return coroner_text(self.locale, key, **values)

    def button(self, key, action, page=0, **values):
        data = CoronerProtectionKeyboardData(action=action, page=page)
        return InlineKeyboardButton(self.t(key, **values), callback_data=data.model_dump())

    def bypass_button(self, page=0):
        if self.protection.limits_bypassed():
            return self.button("limit_bypass_cancel", "bypass_off", page)
        if any(signal.kind == "quota" for signal in self.protection.state.reasons.values()):
            return self.button("limit_bypass_button", "bypass_on", page,
                               duration=duration(self.protection.config.removal_limit_bypass_seconds))
        return None

    def main_buttons(self):
        rows = [[self.button("detectors", "detectors"), self.button("quarantine_button", "quarantine")],
                [self.button("reviews", "review")]]
        bypass = self.bypass_button()
        if bypass is not None:
            rows.append([bypass])
        return rows

    async def display(self, action, page, chat_id, *, notice="", message_id=None,
                      refresh_links=False):
        self.protection.evaluate()
        text, keyboard = self.render(action, page)
        if notice:
            text = notice + "\n\n" + text
        return await self.service.account_links.display(
            text, keyboard, self.t, chat_id, message_id, refresh=refresh_links,
        )

    def _navigation(self, action, page, pages):
        buttons = []
        if page:
            buttons.append(self.button("previous", action, page - 1))
        if page + 1 < pages:
            buttons.append(self.button("next", action, page + 1))
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
                            cooldown=duration(cfg.rejection_cooldown_seconds),
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
                                count=len(entries), percent=limit.global_percent, local_percent=limit.chat_percent,
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
            "protection_blocked" if self.protection.is_blocked() else "protection_clear")) + "\n"
        text += self.protection.bypass_status(self.t) + "\n"
        text += self.protection.approval_status(self.t) + "\n"
        text += self.t("page", page=page + 1, pages=pages) + "\n\n"
        text += "\n\n".join(cards[page * cfg.detector_page_size:(page + 1) * cfg.detector_page_size])
        buttons = self._navigation("detectors", page, pages)
        bypass = self.bypass_button()
        if bypass is not None:
            buttons.append([bypass])
        buttons += [[self.button("update", "detectors", page=page), self.button("back", "status")]]
        return shorten(text, 4000), InlineKeyboardMarkup(buttons)

    def _account_page(self, lines, ids, page, controls):
        # Reserve exactly the controls and navigation needed on each page.
        pages, cursor = [], 0
        while cursor < len(ids):
            available = 100 - controls - bool(pages)
            size = min(self.protection.config.account_links_per_page, available)
            if len(ids) - cursor > size:
                size = min(size, available - 1)
            pages.append(ids[cursor:cursor + size])
            cursor += size
        pages = pages or [[]]
        page = max(0, min(page, len(pages) - 1))
        lines.append(self.t("page", page=page + 1, pages=len(pages)))
        if not ids:
            lines.append(self.t("no_candidates"))
        buttons = [InlineKeyboardButton(str(user_id), url=f"tg://user?id={user_id}") for user_id in pages[page]]
        columns = self.protection.config.account_links_per_row
        rows = [buttons[index:index + columns] for index in range(0, len(buttons), columns)]
        return "\n".join(lines), rows, page, len(pages)

    def _review(self, page):
        state = self.protection.state
        lines = [self.t("review_heading"), self.t("status", status=self.service.state.status),
                 self.t("protection_status", status=self.t(
                     "protection_blocked" if self.protection.is_blocked() else "protection_clear")),
                 self.protection.bypass_status(self.t), self.protection.approval_status(self.t)]
        for signal in list(state.reasons.values())[-4:]:
            text = shorten(self.protection.reason_text(signal), 180)
            lines.append(self.t("review_allowed_reason", reason=text) if self.protection.is_approved(signal) else text)
        ids = sorted(state.quarantine)
        lines.append(self.t("review_counts", users=len(ids),
                            targets=sum(len(candidate.targets) for candidate in state.quarantine.values())))
        grades = dict.fromkeys(("G1", "G2", "G3", "G4"), 0)
        chats = {}
        for user_id, candidate in state.quarantine.items():
            grade = self.service._user_grade(user_id, time.time()).name
            grades[grade] += 1
            for chat_id in candidate.targets:
                chats[chat_id] = chats.get(chat_id, 0) + 1
        lines.append(", ".join(f"{grade}: {count}" for grade, count in grades.items()))
        lines.append(self.t("review_chat_distribution") + " " + shorten(
            ", ".join(f"{chat_id}: {count}" for chat_id, count in sorted(chats.items())), 300))
        bypass = self.bypass_button(page)
        text, buttons, page, pages = self._account_page(lines, ids, page, 4 + (bypass is not None))
        buttons += self._navigation("review", page, pages)
        buttons.append([self.button("approve_all", "approve_all")])
        if bypass is not None:
            buttons.append([bypass])
        buttons.extend([
            [self.button("stop_module", "stop")],
            [self.button("update", "refresh_review", page), self.button("back", "status")],
        ])
        return text, InlineKeyboardMarkup(buttons)

    def _quarantine(self, page):
        ids = sorted(self.protection.state.quarantine)
        text, buttons, page, pages = self._account_page(
            [self.t("quarantine_count", count=len(ids))], ids, page, 4)
        buttons += self._navigation("quarantine", page, pages)
        buttons.extend([
            [self.button("update", "refresh_quarantine", page=page), self.button("reviews", "review")],
            [self.button("stop_module", "stop"), self.button("back", "status")],
        ])
        return text, InlineKeyboardMarkup(buttons)

    def render(self, action, page=0):
        if action == "detectors":
            return self._detectors(page)
        if action == "quarantine":
            return self._quarantine(page)
        return self._review(page)
