import asyncio
import time
from dataclasses import dataclass
from functools import wraps

from telegram import Chat, ChatMember, Update
from telegram.error import BadRequest, ChatMigrated, Forbidden, TelegramError

from src.coroner.CoronerApi import CoronerApi, CoronerInterrupted
from src.coroner.CoronerMessages import CORONER_MESSAGES, coroner_text, duration, shorten
from src.coroner.CoronerModels import (
    CheckJob, CoronerConfig, CoronerState, Participant, Removal, TrackedUser,
)
from src.coroner.CoronerStore import CoronerStore
from src.coroner.CoronerProtection import CoronerProtection
from src.coroner.CoronerProtectionModels import SafetySignal
from src.util.LoggerUtil import LoggerUtil


def is_alive(profile, expected_user_id: int | None = None) -> bool | None:
    """Do not normalize names: invisible Unicode characters are still a name."""
    if expected_user_id is not None and getattr(profile, "id", None) != expected_user_id:
        return None
    name = getattr(profile, "first_name", None)
    return name != "" if isinstance(name, str) else None


def is_present(member: ChatMember) -> bool:
    return member.status in ("member", "administrator", "creator") or (
        member.status == "restricted" and member.is_member
    )


@dataclass
class CoronerError:
    key: str
    text: str
    last_seen: float
    count: int = 1
    chat_id: int | None = None


class CoronerService:
    CONFIG_FILE = "coroner_config.json"
    STATE_FILE = "coroner_state.json"
    ERROR_TTL = 7 * 86400
    HISTORY_TTL = 30 * 86400

    def __init__(self, bot_state, bot, data_folder, locale):
        self.bot_state = bot_state
        self.bot = bot
        self.locale = locale
        self.logger = LoggerUtil.get_logger("Coroner", "Coroner")
        self.store = CoronerStore(data_folder)
        self.config = CoronerConfig()
        self.state = CoronerState()
        self.errors: list[CoronerError] = []
        self._storage_healthy = True
        self._config_healthy = True
        self._revision = 0
        self._saved_revision = 0
        self._write_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._generation = 0
        self._reference_retry_at = 0.0
        self._reference_pending = False
        self.application = None
        try:
            self.config = self.store.load(self.CONFIG_FILE, CoronerConfig)
            self.store.save(self.CONFIG_FILE, self.config.model_dump_json(indent=2))
        except Exception as error:
            self._config_healthy = False
            self._error(None, "config", "config_error", detail=error)
        try:
            self.state = self.store.load(self.STATE_FILE, CoronerState)
            # Upgrade existing per-chat records without resetting anyone's age.
            for chat_id, rows in self.state.participants.items():
                for user_id, row in rows.items():
                    self._remember_user(chat_id, user_id, row.since)
            # Restarting the process never resumes a previously running cleaner.
            if self.state.status == "running":
                self.state.status = "stopped"
                self.store.save(self.STATE_FILE, self.state.model_dump_json(indent=2))
        except Exception as error:
            self._storage_healthy = False
            self._error(None, "storage", "storage_error", detail=error)
        if not self._storage_healthy or not self._config_healthy:
            self.state.status = "error"
        self.api = CoronerApi(
            lambda: self.config.max_requests_per_minute, self._api_error,
            active=lambda: self.application is None or self.application.running,
        )
        self.protection = CoronerProtection(self)
        self.api.on_result = self.protection.record_api
        # Recovery decisions must be durable before polling/webhook handling starts.
        if self._storage_healthy and self._revision != self._saved_revision:
            try:
                self.store.save(self.STATE_FILE, self.state.model_dump_json(indent=2))
                self._saved_revision = self._revision
            except Exception as error:
                self._storage_healthy = False
                self.state.status = "error"
                self._error(None, "storage", "storage_error", detail=error)

    def t(self, key, **values):
        return coroner_text(self.locale, key, **values)

    def _changed(self):
        self._revision += 1

    def _remember_user(self, chat_id, user_id, since):
        user = self.state.users.get(user_id)
        if user is None or since < user.since:
            self.state.users[user_id] = (user.model_copy(update={"since": since, "first_chat_id": chat_id})
                                         if user is not None else TrackedUser(since=since, first_chat_id=chat_id))
            self._changed()

    def _user_grade(self, user_id, now):
        return self.config.grade_for(self.state.users[user_id].since, now)

    def _error(self, chat_id, key, message, *, detail=None, **values):
        text = self.t(message, **values)
        if chat_id is not None:
            text = self.t("error_chat", chat_id=chat_id, text=text)
        self.logger.error("%s%s", text, (
            f" ({type(detail).__name__}: {CoronerApi.safe_detail(detail)})"
            if detail is not None else ""
        ))
        now = time.time()
        entries = self._recent_errors(now)
        previous = next((entry for entry in entries
                         if entry.key == key and entry.chat_id == chat_id), None)
        if previous is not None:
            entries.remove(previous)
            previous.count += 1
            previous.last_seen = now
            previous.text = text
            entries.append(previous)
        else:
            entries.append(CoronerError(key, text, now, chat_id=chat_id))
        self.errors = entries[-5:]

    def _recent_errors(self, now=None):
        now = time.time() if now is None else now
        self.errors = [entry for entry in self.errors
                       if entry.last_seen > now - self.ERROR_TTL]
        return self.errors

    def _api_error(self, chat_id, operation, params, error, background):
        kind = self.api.error_kind(error)
        operation_key = f"operation_{operation}"
        if operation_key not in CORONER_MESSAGES:
            operation_key = "operation_default"
        user_id = params.get("user_id")
        subject = self.t("api_subject", user_id=user_id) if user_id else ""
        self._error(
            chat_id, f"api:{operation}:{kind}:{user_id}", "api_error", detail=error,
            operation=self.t(operation_key), subject=subject, reason=self.t(kind),
            action=self.t("retry_action" if background else "ui_action"),
        )

    async def save(self, force=False) -> bool:
        if not self._storage_healthy:
            return False
        async with self._write_lock:
            if not force and self._saved_revision == self._revision:
                return True
            revision = self._revision
            snapshot = self.state.model_dump_json(indent=2)
            try:
                await asyncio.to_thread(self.store.save, self.STATE_FILE, snapshot)
            except Exception as error:
                self._storage_healthy = False
                self.state.status = "error"
                self._generation += 1
                self._error(None, "storage", "storage_error", detail=error)
                return False
            self._saved_revision = revision
            return True

    async def _save_config(self, config):
        async with self._write_lock:
            await asyncio.to_thread(self.store.save, self.CONFIG_FILE, config.model_dump_json(indent=2))
        self.config = config
        self._config_healthy = True

    async def _load_config(self) -> bool:
        try:
            config = await asyncio.to_thread(self.store.load, self.CONFIG_FILE, CoronerConfig)
            await self._save_config(config)
        except Exception as error:
            self._config_healthy = False
            self.state.status = "error"
            self._generation += 1
            self._changed()
            self._error(None, "config", "config_error", detail=error)
            await self.save()
            return False
        self.protection.collect(time.time())
        return True

    def install(self, application):
        self.application = application
        if application.job_queue is None:
            raise ValueError("Coroner requires the application job queue")
        application.job_queue.run_repeating(
            self._maintenance, interval=2, first=1, name="coroner-maintenance",
            job_kwargs={"max_instances": 1, "coalesce": True},
        )
        self._schedule_worker(application.job_queue, 1)

    def _schedule_worker(self, job_queue, delay):
        # A late one-shot must still run: it schedules the next worker.
        job_queue.run_once(
            self._worker, delay, name="coroner-worker",
            job_kwargs={
                "id": f"coroner-worker-{time.monotonic_ns()}",
                "misfire_grace_time": None,
            },
        )

    def _sync_chats(self):
        current = set(self.bot_state.moderated_chat_ids)
        previous = set(self.state.moderated_chats)
        if current == previous:
            return
        for chat_id in current - previous:
            for row in self.state.participants.get(chat_id, {}).values():
                row.active = True
                row.status = "unknown"
                row.next_check_at = 0
                row.last_successful_check = None
                row.generation += 1
        for key, job in list(self.state.queue.items()):
            if job.chat_id not in current:
                del self.state.queue[key]
        self.state.moderated_chats = sorted(current)
        self._changed()

    def _observe(self, chat_id, user_id, at, update_id, *, active=True,
                 status="member", joined=False, message_only=False):
        rows = self.state.participants.setdefault(chat_id, {})
        row = rows.get(user_id)
        if row is not None and (at, update_id) < (row.last_event_at, row.last_update_id):
            if joined and row.active and row.joined_at is None and at > row.last_departure_at:
                # A delayed join can provide an exact date after a newer message
                # first introduced this participant. It is not another rejoin.
                row.joined_at = at
                self._remember_user(chat_id, user_id, row.since)
                self._changed()
            return
        if row is not None and row.active and message_only:
            return  # Ordinary messages need no repeated full-roster JSON writes.
        if row is None:
            row = Participant(first_seen_at=time.time())
            rows[user_id] = row
        # Both Telegram membership and service-message updates can describe one join.
        same_join = row.joined_at is not None and abs(row.joined_at - at) <= 1
        if joined and not same_join:
            row.joined_at = at
            row.first_seen_at = time.time()
            row.generation += 1
            row.last_successful_check = None
            row.next_check_at = 0
            self.state.queue.pop(f"{chat_id}:{user_id}", None)
        elif active and not row.active:
            row.joined_at = at if joined else None
            row.first_seen_at = time.time()
            row.generation += 1
            row.last_successful_check = None
            row.next_check_at = 0
        row.active = active
        row.status = status
        row.last_event_at = at
        row.last_update_id = update_id
        if not active:
            row.last_departure_at = at
        key = f"{chat_id}:{user_id}"
        queued = self.state.queue.get(key)
        if not active and queued is not None and queued.stage != "removing":
            self.state.queue.pop(key, None)
        self._remember_user(chat_id, user_id, row.since)
        self._changed()

    async def observe_update(self, update: Update, context):
        try:
            self._sync_chats()
            message = update.effective_message
            if message is not None and message.migrate_to_chat_id:
                if self.bot_state.is_chat_moderated(message.chat_id):
                    await self.migrate_chat(message.chat_id, message.migrate_to_chat_id)
            elif message is not None and message.migrate_from_chat_id:
                if self.bot_state.is_chat_moderated(message.migrate_from_chat_id):
                    await self.migrate_chat(message.migrate_from_chat_id, message.chat_id)
            chat = update.effective_chat
            if chat is None or chat.type not in (Chat.GROUP, Chat.SUPERGROUP):
                return
            if not self.bot_state.is_chat_moderated(chat.id):
                return
            rows = self.state.participants.setdefault(chat.id, {})
            if self.bot.id not in rows:
                rows[self.bot.id] = Participant(first_seen_at=time.time())
                self._remember_user(chat.id, self.bot.id, rows[self.bot.id].since)
                self._changed()
            membership = update.chat_member or update.my_chat_member
            if membership is not None:
                member = membership.new_chat_member
                self._observe(
                    chat.id, member.user.id, membership.date.timestamp(), update.update_id,
                    active=is_present(member), status=member.status,
                    joined=is_present(member) and not is_present(membership.old_chat_member),
                )
            if message is not None and (update.message or update.edited_message):
                at = (message.edit_date or message.date).timestamp()
                if message.from_user is not None and message.sender_chat is None:
                    self._observe(chat.id, message.from_user.id, at, update.update_id, message_only=True)
                    if update.message and not message.new_chat_members and message.left_chat_member is None:
                        self.protection.observe_activity(message.from_user.id, message.date.timestamp())
                for user in message.new_chat_members:
                    self._observe(chat.id, user.id, at, update.update_id, joined=True)
                if message.left_chat_member is not None:
                    self._observe(chat.id, message.left_chat_member.id, at, update.update_id,
                                  active=False, status="left")
            await self.save()
        except Exception as error:
            self._error(None, "observer", "worker_error", detail=error)

    async def migrate_chat(self, old_id, new_id):
        if old_id == new_id:
            return
        self.bot_state.migrate_moderated_chat(old_id, new_id)
        old_rows = self.state.participants.pop(old_id, {})
        rows = self.state.participants.setdefault(new_id, {})
        for user_id, row in old_rows.items():
            if user_id not in rows or row.last_event_at > rows[user_id].last_event_at:
                rows[user_id] = row
        for key, job in list(self.state.queue.items()):
            if job.chat_id == old_id:
                del self.state.queue[key]
                job.chat_id = new_id
                other = self.state.queue.get(job.key)
                if other is None or job.enqueued_at < other.enqueued_at:
                    self.state.queue[job.key] = job
        for entry in self.state.removals:
            if entry.chat_id == old_id:
                entry.chat_id = new_id
        for user in self.state.users.values():
            if user.first_chat_id == old_id:
                user.first_chat_id = new_id
        for candidate in self.state.protection.quarantine.values():
            for targets in (candidate.targets, candidate.approved_targets):
                if old_id in targets:
                    targets[new_id] = targets.pop(old_id)
        # Previously approved chat IDs never silently expand to a new destination.
        for request in self.state.protection.requests.values():
            if request.state == "pending":
                request.state = "superseded"
                request.decided_at = time.time()
        self.state.protection.epoch += 1
        self.state.protection.current_request_id = None
        for reservation in self.state.protection.reservations:
            if reservation.chat_id == old_id:
                reservation.chat_id = new_id
        self.state.protection.populations_at = 0
        if self.config.reference_chat_id == old_id:
            config = self.config.model_copy(update={"reference_chat_id": new_id})
            await self._save_config(config)
        self.state.moderated_chats = sorted(set(self.bot_state.moderated_chat_ids))
        self._generation += 1
        self._changed()
        await self.save()

    def _enqueue(self, chat_id, user_id, row, source="scheduled") -> bool:
        key = f"{chat_id}:{user_id}"
        if key in self.state.queue:
            return False
        self.state.queue[key] = CheckJob(
            chat_id=chat_id, user_id=user_id, generation=row.generation,
            enqueued_at=time.time(), source=source,
        )
        self._changed()
        return True

    def _remember_member(self, chat_id, member):
        if not self.bot_state.is_chat_moderated(chat_id) or not is_present(member):
            return
        rows = self.state.participants.setdefault(chat_id, {})
        if member.user.id not in rows:
            rows[member.user.id] = Participant(first_seen_at=time.time(), status=member.status)
            self._changed()
        self._remember_user(chat_id, member.user.id, rows[member.user.id].since)

    async def enqueue_grade(self, grade):
        if self.state.status != "running":
            return 0, 0
        added = existing = 0
        now = time.time()
        for chat_id in sorted(set(self.bot_state.moderated_chat_ids)):
            for user_id, row in self.state.participants.get(chat_id, {}).items():
                if not row.active or user_id == self.bot.id:
                    continue
                if grade != "ALL" and self._user_grade(user_id, now).name != grade:
                    continue
                if self._enqueue(chat_id, user_id, row, "manual"):
                    added += 1
                else:
                    existing += 1
        await self.save()
        return added, existing

    async def _maintenance(self, context):
        try:
            self._sync_chats()
            now = time.time()
            self._recent_errors(now)
            self.protection.tick(now)
            self.protection.schedule_notifications()
            horizon = max(self.HISTORY_TTL, self.config.protection.removal_statistics_days * 86400)
            history = [entry for entry in self.state.removals if entry.removed_at > now - horizon]
            if len(history) != len(self.state.removals):
                self.state.removals = history
                self._changed()
            if self.state.status == "running":
                for chat_id in self.bot_state.moderated_chat_ids:
                    for user_id, row in self.state.participants.get(chat_id, {}).items():
                        if not row.active or user_id == self.bot.id:
                            continue
                        grade = self._user_grade(user_id, now)
                        due = (row.last_successful_check + grade.check_interval_seconds
                               if row.last_successful_check is not None else 0)
                        if due != row.next_check_at:
                            row.next_check_at = due
                            self._changed()
                        if due <= now:
                            self._enqueue(chat_id, user_id, row)
            await self.save()
        except Exception as error:
            self._error(None, "maintenance", "worker_error", detail=error)

    def     _guard(self, generation, job=None, *, running=True):
        if generation != self._generation or not self._storage_healthy or not self._config_healthy:
            raise CoronerInterrupted()
        if running and self.state.status != "running":
            raise CoronerInterrupted()
        if job is not None:
            row = self.state.participants.get(job.chat_id, {}).get(job.user_id)
            if (not self.bot_state.is_chat_moderated(job.chat_id) or row is None
                    or row.generation != job.generation or self.state.queue.get(job.key) is not job):
                raise CoronerInterrupted()

    async def set_reference(self, user_id, chat_id):
        async with self._control_lock:
            await self.stop()
            if not await self._load_config():
                return False
            config = CoronerConfig.model_validate({
                **self.config.model_dump(), "reference_user_id": user_id, "reference_chat_id": chat_id,
            })
            try:
                await self._save_config(config)
            except Exception as error:
                self._error(None, "config", "config_error", detail=error)
                return False
            self.state.checks_since_reference = 0
            self.state.last_reference_at = None
            self.state.last_reference_alive = None
            self._reference_pending = False
            self._reference_retry_at = 0
            self._changed()
            await self.save()
            return True

    async def stop(self):
        self._generation += 1
        self.protection._last_collection_at = None
        if self.state.status != "error":
            self.state.status = "stopped"
        self._changed()
        await self.save()

    async def start(self) -> str:
        async with self._control_lock:
            if self.state.status == "running":
                return "already_running"
            if not self._storage_healthy or not await self._load_config():
                return "start_failed"
            if self.config.reference_user_id is None:
                return "ref_required"
            self._generation += 1
            self.protection._last_collection_at = None
            generation = self._generation
            try:
                alive = await self._check_reference(generation, starting=True)
                self._guard(generation, running=False)
            except CoronerInterrupted:
                return "start_failed"
            if alive is not True:
                return "start_failed"
            self.state.status = "running"
            self._changed()
            if not await self.save():
                return "start_failed"
            return "started"

    async def _check_reference(self, generation, *, starting=False):
        user_id, chat_id = self.config.reference_user_id, self.config.reference_chat_id
        guard = lambda: self._guard(generation, running=not starting)
        alive = None
        try:
            if user_id is not None and chat_id is not None:
                member = await self.api.call(
                    self.bot.get_chat_member, chat_id=chat_id, user_id=user_id,
                    guard=guard, priority=-10, background=True,
                )
                self._remember_member(chat_id, member)
                alive = is_alive(member.user, user_id)
                if alive is False:
                    profile = await self.api.call(
                        self.bot.get_chat, chat_id=user_id, guard=guard,
                        priority=-10, background=True,
                    )
                    alive = False if is_alive(profile, user_id) is False else None
        except CoronerInterrupted:
            raise
        except Exception:
            alive = None
        guard()
        self.state.last_reference_at = time.time()
        self.state.last_reference_alive = alive
        self._reference_pending = alive is not True
        if alive is False:
            self.state.status = "error"
            self._generation += 1
            self._error(None, "reference-deleted", "reference_failed", user_id=user_id)
            self.logger.critical("CORONER EMERGENCY STOP: reference user %s detected as deleted", user_id)
        elif alive is None:
            self._reference_retry_at = time.time() + self.config.retry_delay_seconds
            self._error(None, "reference-unknown", "reference_unknown")
        else:
            self.state.checks_since_reference = 0
            self._reference_retry_at = 0
        self._changed()
        await self.save()
        return alive

    async def _worker(self, context):
        delay = 0.5
        try:
            if self.state.status != "running":
                return
            generation = self._generation
            if self._reference_pending or self.state.checks_since_reference >= self.config.reference_check_every:
                if time.time() < self._reference_retry_at:
                    return
                if await self._check_reference(generation) is not True:
                    return
            now = time.time()
            candidates = [job for job in self.state.queue.values() if job.not_before <= now]
            if not candidates:
                return
            job = min(candidates, key=lambda entry: entry.enqueued_at)
            delay = 0.01
            try:
                self._guard(generation, job)
                await self._process_job(job, generation)
            except CoronerInterrupted:
                # Keep valid jobs on stop; discard obsolete joins or abandoned chats.
                row = self.state.participants.get(job.chat_id, {}).get(job.user_id)
                if (not self.bot_state.is_chat_moderated(job.chat_id) or row is None
                        or row.generation != job.generation):
                    self._finish_job(job)
            except ChatMigrated as error:
                await self.migrate_chat(job.chat_id, error.new_chat_id)
            except Exception as error:
                job.attempts += 1
                job.not_before = time.time() + self.api.retry_delay(error, self.config.retry_delay_seconds)
                self._changed()
                if not isinstance(error, TelegramError):
                    self._error(job.chat_id, "worker", "worker_error", detail=error)
            await self.save()
        except CoronerInterrupted:
            pass
        except Exception as error:
            self._error(None, "worker", "worker_error", detail=error)
        finally:
            # One-shot jobs avoid an immortal application task blocking shutdown.
            if self.application is not None and self.application.running:
                self._schedule_worker(context.job_queue, delay)

    def _finish_job(self, job):
        if self.state.queue.get(job.key) is job:
            del self.state.queue[job.key]
            self._changed()

    def _complete_check(self, job, row):
        row.last_successful_check = time.time()
        grade = self._user_grade(job.user_id, row.last_successful_check)
        row.next_check_at = row.last_successful_check + grade.check_interval_seconds
        self._finish_job(job)
        self._changed()

    async def _process_job(self, job, generation):
        guard = lambda: self._guard(generation, job)
        row = self.state.participants[job.chat_id][job.user_id]
        event_version = (row.last_event_at, row.last_update_id)
        try:
            member = await self.api.call(
                self.bot.get_chat_member, chat_id=job.chat_id, user_id=job.user_id,
                error_chat_id=job.chat_id, background=True, priority=10, guard=guard,
            )
        finally:
            if job.user_id != self.config.reference_user_id:
                self.state.checks_since_reference += 1
                self._changed()
        guard()
        if event_version != (row.last_event_at, row.last_update_id):
            raise CoronerInterrupted()
        row.status = member.status
        if job.user_id == self.config.reference_user_id:
            if await self._check_reference(generation) is True:
                if is_present(member):
                    self._complete_check(job, row)
                else:
                    row.active = False
                    self._finish_job(job)
                    self._changed()
            return
        if not is_present(member):
            row.active = False
            self.protection.finish_target(job.user_id, job.chat_id)
            if job.stage == "removing":
                self._error(job.chat_id, f"uncertain:{job.id}", "uncertain_removal", user_id=job.user_id)
            self._finish_job(job)
            self._changed()
            return
        row.active = True
        alive = is_alive(member.user, job.user_id)
        self.protection.record_check(job.user_id, job.chat_id, alive)
        if alive is True:
            self._complete_check(job, row)
            return
        if alive is False:
            profile = await self.api.call(
                self.bot.get_chat, chat_id=job.user_id, error_chat_id=job.chat_id,
                background=True, priority=10, guard=guard,
            )
            alive = is_alive(profile, job.user_id)
            guard()
            if alive is True:
                self.state.users[job.user_id].last_alive_at = time.time()
                self.protection.cancel_candidate(job.user_id)
        if alive is not False:
            self.protection.record_check(job.user_id, job.chat_id, None, primary=False)
            self._error(job.chat_id, f"profile:{job.user_id}", "profile_unknown", user_id=job.user_id)
            job.not_before = time.time() + self.config.retry_delay_seconds
            self._changed()
            return
        if member.status in ("administrator", "creator"):
            self._error(job.chat_id, f"protected:{job.user_id}", "protected_member", user_id=job.user_id)
            self._complete_check(job, row)
            return
        candidate = self.protection.enter(job, row)
        if candidate is None:
            self._complete_check(job, row)
            return
        if not self.protection.permitted(candidate, job.chat_id, row.generation):
            job.not_before = min(candidate.ready_at, time.time() + self.config.protection.recheck_seconds)
            if job.not_before <= time.time():
                job.not_before = time.time() + self.config.protection.recheck_seconds
            self._changed()
            await self.save()
            return
        await self.cremate(job, row, generation)

    async def cremate(self, job: CheckJob, row: Participant, generation: int):
        if job.user_id in (self.bot.id, self.config.reference_user_id):
            raise CoronerInterrupted()
        candidate = self.state.protection.quarantine.get(job.user_id)
        if candidate is None or not self.protection.permitted(candidate, job.chat_id, row.generation):
            raise CoronerInterrupted()
        if await self._check_reference(generation) is not True:
            return
        def guard():
            self._guard(generation, job)
            if not self.protection.permitted(candidate, job.chat_id, row.generation):
                raise CoronerInterrupted()
        event_version = (row.last_event_at, row.last_update_id)
        # Re-read membership after confirmation and the reference check. Never
        # intentionally undo an existing moderation ban or demote administrators.
        member = await self.api.call(
            self.bot.get_chat_member, chat_id=job.chat_id, user_id=job.user_id,
            error_chat_id=job.chat_id, background=True, priority=10, guard=guard,
        )
        guard()
        if event_version != (row.last_event_at, row.last_update_id):
            raise CoronerInterrupted()
        if not is_present(member):
            row.active = False
            self.protection.finish_target(job.user_id, job.chat_id)
            self._finish_job(job)
            self._changed()
            return
        if is_alive(member.user, job.user_id) is not False:
            if is_alive(member.user, job.user_id) is True:
                self.protection.cancel_candidate(job.user_id)
            self._error(job.chat_id, f"profile:{job.user_id}", "profile_unknown", user_id=job.user_id)
            job.not_before = time.time() + self.config.retry_delay_seconds
            self._changed()
            return
        if member.status in ("administrator", "creator"):
            self.protection.finish_target(job.user_id, job.chat_id)
            self._error(job.chat_id, f"protected:{job.user_id}", "protected_member", user_id=job.user_id)
            self._complete_check(job, row)
            return
        grade = self._user_grade(job.user_id, time.time()).name
        def removal_guard():
            guard()
            if not row.active or event_version != (row.last_event_at, row.last_update_id):
                raise CoronerInterrupted()

        reservation = await self.protection.reserve(job, removal_guard)
        if reservation is None:
            job.not_before = time.time() + self.config.protection.recheck_seconds
            self._changed()
            return
        dispatched = False

        @wraps(self.bot.unban_chat_member)
        async def remove(**params):
            nonlocal dispatched
            dispatched = True
            return await self.bot.unban_chat_member(**params)

        try:
            if self.config.dry_run:
                removal_guard()
                reservation.state = "completed"
                self.logger.info("CORONER dry_run: would remove user %s from chat %s; grade=%s source=%s operation=%s",
                                 job.user_id, job.chat_id, grade, job.source, reservation.id)
                self.protection.finish_target(job.user_id, job.chat_id)
                self._complete_check(job, row)
                return
            job.stage = "removing"
            self._changed()
            if not await self.save(force=True):
                raise CoronerInterrupted()

            # The fresh membership check excludes existing bans; the guard
            # catches received membership events before the request is sent.
            result = await self.api.call(
                remove, chat_id=job.chat_id, user_id=job.user_id,
                only_if_banned=False, error_chat_id=job.chat_id, background=True,
                priority=10, guard=removal_guard,
            )
            if result is not True:
                raise RuntimeError("Telegram did not confirm removal")
            reservation.state = "completed"
            reservation.at = time.time()
        except (BadRequest, Forbidden):
            reservation.state = "released"
            job.stage = "check"
            raise
        except Exception:
            reservation.state = "uncertain" if dispatched else "released"
            if dispatched:
                reservation.at = time.time()
            job.stage = "check"
            if dispatched:
                self.protection.trip(SafetySignal(key="uncertain-removal", kind="interrupted", at=time.time(),
                                                  user_id=job.user_id, chat_id=job.chat_id), new_incident=True)
            raise
        finally:
            self._changed()
            await self.save(force=True)
        if not any(entry.operation_id == reservation.id for entry in self.state.removals):
            self.state.removals.append(Removal(
                operation_id=reservation.id, chat_id=job.chat_id, user_id=job.user_id,
                grade=grade, removed_at=time.time(),
            ))
        if row.generation == job.generation:
            row.active = False
            row.status = "left"
        self._finish_job(job)
        self.protection.finish_target(job.user_id, job.chat_id)
        self._changed()
        await self.save(force=True)
        self.logger.info("CORONER removed user %s from chat %s; grade=%s operation=%s",
                         job.user_id, job.chat_id, grade, job.id)

    async def authorized(self, user_id, chat_id):
        async def telegram_request(method, **params):
            if method.__name__ == "get_chat_administrators" and params["chat_id"] > 0:
                return []  # Private chats have no Telegram administrators.
            result = await self.api.call(method, error_chat_id=params.get("chat_id", chat_id), **params)
            if method.__name__ == "get_chat_administrators":
                for member in result:
                    self._remember_member(params["chat_id"], member)
                await self.save()
            return result

        targets = set(self.bot_state.moderated_chat_ids)
        lookup_chats = sorted(targets) if targets else [chat_id]
        for target in lookup_chats:
            if not await self.bot_state.is_admin(user_id, target, telegram_request=telegram_request):
                return False
        return targets == set(self.bot_state.moderated_chat_ids)

    async def status_text(self, locale):
        t = lambda key, **values: coroner_text(locale, key, **values)
        chat_ids = set(self.bot_state.moderated_chat_ids)
        totals = {}
        for chat_id in sorted(chat_ids):
            try:
                totals[chat_id] = await self.api.call(
                    self.bot.get_chat_member_count, chat_id=chat_id, error_chat_id=chat_id,
                )
            except Exception:
                pass
        now = time.time()
        monitored = set()
        observed_total = member_total = 0
        complete_counts = bool(chat_ids)
        for chat_id in sorted(chat_ids):
            rows = self.state.participants.get(chat_id, {})
            active = {user_id: row for user_id, row in rows.items() if row.active}
            # Telegram counts memberships, including this bot, separately in each chat.
            observed = len(set(active) | {self.bot.id})
            total = totals.get(chat_id)
            if type(total) is not int or total <= 0:
                complete_counts = False
            elif observed > total:
                complete_counts = False
                self._error(chat_id, "count-mismatch", "count_mismatch")
            else:
                member_total += total
                observed_total += observed
            monitored.update(user_id for user_id in active if user_id != self.bot.id)
        untracked = (f"{100 * (member_total - observed_total) / member_total:.2f}%"
                     if complete_counts else t("unavailable"))
        jobs = [job for job in self.state.queue.values() if job.chat_id in chat_ids]
        counts = {grade.name: 0 for grade in self.config.grades}
        removed = dict.fromkeys(counts, 0)
        for user_id in monitored:
            counts[self._user_grade(user_id, now).name] += 1
        removed_users = set()
        for entry in sorted(self.state.removals, key=lambda entry: entry.removed_at):
            if entry.removed_at > now - self.HISTORY_TTL and entry.user_id not in removed_users:
                removed[entry.grade] += 1
                removed_users.add(entry.user_id)
        lines = [t("heading", count=len(chat_ids)), t("status", status=self.state.status),
                 t("dry_run", value=t("yes" if self.config.dry_run else "no"))]
        protection = self.state.protection
        lines.append(t("protection_status", status=t("protection_blocked" if protection.blocked else "protection_clear")))
        lines.append(t("quarantine_count", count=len(protection.quarantine)))
        if protection.blocked:
            for signal in list(protection.reasons.values())[-2:]:
                lines.append(shorten(self.protection.reason_text(signal), 220))
        if self.config.reference_user_id is None:
            lines.append(t("reference_missing"))
        else:
            lines.append(t("reference", user_id=self.config.reference_user_id,
                           chat_id=self.config.reference_chat_id, every=self.config.reference_check_every))
        if self.state.last_reference_at is None:
            lines.append(t("reference_never"))
        else:
            result = {True: "alive", False: "deleted", None: "unknown"}[self.state.last_reference_alive]
            lines.append(t("reference_last", result=t(result), age=duration(now - self.state.last_reference_at)))
        if self._reference_pending:
            lines.append(t("reference_waiting"))
        lines.extend(["", t("monitored", count=len(monitored)), t("untracked", value=untracked)])
        lines.extend(t("grade", grade=name, count=count) for name, count in counts.items())
        lines.append(t("queue", count=len(jobs), wait=duration(max(
            (now - job.enqueued_at for job in jobs), default=0,
        ))))
        lines.append(t("removed", counts=", ".join(f"{name}: {count}" for name, count in removed.items())))
        entries = sorted(self._recent_errors(now), key=lambda entry: entry.last_seen, reverse=True)
        if entries:
            lines.extend(["", t("errors")])
            for entry in entries:
                repeated = t("repeated", count=entry.count) if entry.count > 1 else ""
                lines.append(t("error_entry", age=duration(now - entry.last_seen),
                               text=shorten(entry.text, 420), repeated=repeated))
        return shorten("\n".join(lines), 4000)
