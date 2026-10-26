import asyncio
import math
import random
import time
from dataclasses import dataclass
from functools import wraps

from telegram import Chat, ChatMember, Update
from telegram.error import BadRequest, ChatMigrated, Forbidden, RetryAfter, TelegramError

from src.coroner.CoronerApi import CoronerApi, CoronerInterrupted
from src.coroner.CoronerAccountLinks import CoronerAccountLinks
from src.coroner.CoronerDisplay import CHAT_REFERENCE, chat_label, log_text, render_html
from src.coroner.CoronerMessages import CORONER_MESSAGES, coroner_text, duration, shorten
from src.coroner.CoronerModels import (
    CheckJob, CoronerConfig, CoronerState, Removal, TrackedUser,
)
from src.coroner.CoronerStore import CoronerStore
from src.coroner.CoronerStateStore import CoronerStateStore
from src.coroner.CoronerProtection import CoronerProtection
from src.coroner.CoronerProtectionModels import SafetySignal
from src.util.LoggerUtil import LoggerUtil
from src.util.data.BotState import CachedChannel


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
class MembershipEvent:
    at: float
    update_id: int
    joined_at: float | None = None


@dataclass
class CoronerError:
    key: str
    text: str
    last_seen: float
    count: int = 1
    chat_id: int | None = None


class CoronerService:
    CONFIG_FILE = "coroner_config.json"
    ERROR_TTL = 7 * 86400
    HISTORY_TTL = 30 * 86400

    def __init__(self, bot_state, bot, data_folder, locale):
        self.bot_state = bot_state
        self.bot = bot
        self.locale = locale
        self.logger = LoggerUtil.get_logger("Coroner", "Coroner")
        self.store = CoronerStore(data_folder)
        self.state_store = CoronerStateStore(data_folder)
        self._closed = False
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
        self._membership_events: dict[tuple[int, int], MembershipEvent] = {}
        self._chat_name_locks: dict[int, asyncio.Lock] = {}
        self.application = None
        try:
            self.config = self.store.load(self.CONFIG_FILE, CoronerConfig)
            self.store.save(self.CONFIG_FILE, self.config.model_dump_json(indent=2))
        except Exception as error:
            self._config_healthy = False
            self._error(None, "config", "config_error", detail=error)
        try:
            self.state = self.state_store.load()
            self._refresh_grades(time.time())
        except Exception as error:
            self._storage_healthy = False
            self._error(None, "storage", "storage_error", detail=error)
        if not self._storage_healthy or not self._config_healthy:
            self.state.status = "error"
        # Resume saved work only after a fresh reference check in this process.
        self._reference_pending = self.state.status == "running"
        self.api = CoronerApi(
            lambda: self.config.max_requests_per_minute, self._api_error,
            active=lambda: self.application is None or self.application.running,
            invalid_response_retries=lambda: self.config.invalid_response_retries,
            invalid_response_retry_delay=lambda: self.config.invalid_response_retry_delay_seconds,
        )
        self.protection = CoronerProtection(self)
        self.account_links = CoronerAccountLinks(self)
        if self._storage_healthy:
            self.bot_state.set_message_history_tracking(self.is_tracking_member)
        # Recovery decisions must be durable before polling/webhook handling starts.
        if self._storage_healthy and self._revision != self._saved_revision:
            try:
                self.state_store.save(self.state.model_dump(mode="json"))
                self._saved_revision = self._revision
            except Exception as error:
                self._storage_healthy = False
                self.state.status = "error"
                self._error(None, "storage", "storage_error", detail=error)

    def t(self, key, **values):
        return coroner_text(self.locale, key, **values)

    chat_label = staticmethod(chat_label)

    def moderated_chat_ids(self):
        # Private chat/user IDs cannot be Coroner membership scopes.
        return {chat_id for chat_id in self.bot_state.moderated_chat_ids if chat_id < 0}

    def is_tracking_member(self, chat_id, user_id):
        user = self.state.users.get(user_id)
        return user is not None and chat_id in user.chat_ids and chat_id in self.moderated_chat_ids()

    async def display_text(self, text):
        titles = {}
        for chat_id in dict.fromkeys(int(match[1]) for match in CHAT_REFERENCE.finditer(text)):
            async with self._chat_name_locks.setdefault(chat_id, asyncio.Lock()):
                cached = self.bot_state.get_cached_channel(chat_id)
                if cached is None or not cached.title:
                    try:
                        chat = await self.api.call(self.bot.get_chat, chat_id=chat_id, error_chat_id=chat_id)
                        title = chat.title or " ".join(filter(None, (chat.first_name, chat.last_name))) or chat.username
                        if title:
                            cached = CachedChannel(id=chat_id, title=title)
                            self.bot_state.set_cached_channel(cached)
                    except (TelegramError, CoronerInterrupted):
                        pass  # The API wrapper records the cause; IDs stay in the application log.
                titles[chat_id] = cached.title if cached and cached.title else self.t("unknown_chat")
        return render_html(text, titles)

    def _changed(self):
        self._revision += 1

    def _remember_user(self, chat_id, user_id, since):
        user = self.state.users.get(user_id)
        if user is None:
            user = TrackedUser(since=since, first_chat_id=chat_id, chat_ids=[chat_id])
            self.state.users[user_id] = user
            self._changed()
        elif since < user.since:
            user.since, user.first_chat_id = since, chat_id
            self._changed()
        self._user_grade(user_id, time.time())
        return user

    def _user_grade(self, user_id, now):
        user = self.state.users[user_id]
        grade = self.config.grade_for(user.since, now)
        if user.last_grade != grade.name:
            previous = user.last_grade
            user.last_grade = grade.name
            self._changed()
            if previous is not None:
                self.logger.info(
                    "CORONER user %s grade changed %s -> %s; first_chat=%s age_seconds=%.0f",
                    user_id, previous, grade.name, user.first_chat_id, max(0, now - user.since),
                )
        return grade

    def _refresh_grades(self, now):
        for user_id in self.state.users:
            self._user_grade(user_id, now)

    def _mark_not_present(self, chat_id, user_id, status, source):
        user = self.state.users.get(user_id)
        if user is None or chat_id not in user.chat_ids:
            return
        self.logger.info("CORONER user %s no longer monitored in chat %s; status=%s source=%s",
                         user_id, chat_id, status, source)
        user.chat_ids.remove(chat_id)
        self.bot_state.remove_message_edit_history(chat_id, user_id)
        self.protection.finish_target(user_id, chat_id)
        self._membership_events.pop((chat_id, user_id), None)
        if not self._moderated_chats_for(user):
            self.state.queue.pop(str(user_id), None)
            self.state.protection.quarantine.pop(user_id, None)
            self.bot_state.prune_message_edit_histories()
        if not user.chat_ids:
            self.state.users.pop(user_id, None)
            self.logger.info("CORONER user %s removed from monitoring: no known chats remain", user_id)
        self._changed()

    def _error(self, chat_id, key, message, *, detail=None, **values):
        text = self.t(message, **values)
        if chat_id is not None:
            text = self.t("error_chat", chat_id=self.chat_label(chat_id), text=text)
        self.logger.error("%s%s", log_text(text), (
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
        user_id = params.get("user_id")
        if (background and operation in ("get_chat_member", "get_chat", "ban_chat_member")
                and (user_id is not None or params.get("chat_id", 0) > 0)
                and (user_id or params.get("chat_id")) != self.config.reference_user_id
                and CoronerApi.is_missing_member(error)):
            return  # The worker removes only this membership and immediately tries another chat.
        kind = self.api.error_kind(error)
        operation_key = f"operation_{operation}"
        if operation_key not in CORONER_MESSAGES:
            operation_key = "operation_default"
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
            try:
                snapshot = self.state.model_dump(mode="json")
                await asyncio.to_thread(self.state_store.save, snapshot)
            except Exception as error:
                self._storage_healthy = False
                self.state.status = "error"
                self._generation += 1
                self._error(None, "storage", "storage_error", detail=error)
                return False
            self._saved_revision = revision
            return True

    def close(self):
        if self._closed:
            return
        try:
            if self._storage_healthy:
                self.state_store.save(self.state.model_dump(mode="json"))
        except Exception as error:
            self._storage_healthy = False
            self._error(None, "storage", "storage_error", detail=error)
        finally:
            self.state_store.close()
            self._closed = True

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

    def _moderated_chats_for(self, user):
        moderated = self.moderated_chat_ids()
        return [chat_id for chat_id in user.chat_ids if chat_id in moderated]

    def _sync_chats(self):
        current = self.moderated_chat_ids()
        previous = set(self.state.moderated_chats)
        if current != previous:
            abandoned = previous - current
            for user_id, user in list(self.state.users.items()):
                for chat_id in list(user.chat_ids):
                    if chat_id in abandoned:
                        self._mark_not_present(chat_id, user_id, "abandoned", "moderation_disabled")
            self.state.moderated_chats = sorted(current)
            self._changed()
        # Imports can contain chats that have not been enabled with /moderate yet.
        # Keep those memberships, but never enqueue or retain checks for them alone.
        for job in list(self.state.queue.values()):
            user = self.state.users.get(job.user_id)
            if user is None or not self._moderated_chats_for(user):
                self._finish_job(job)

    def _membership_changed(self, user_id, user):
        user.generation += 1
        queued = self.state.queue.get(str(user_id))
        if queued is not None:
            self.state.queue[str(user_id)] = queued.model_copy(update={
                "generation": user.generation, "chat_id": None,
            })
        # Keep the entry until activity detection can inspect this update.
        # Its old generation already prevents a ban; maintenance prunes stale targets.
        self._changed()

    def _observe(self, chat_id, user_id, at, update_id, *, active=True,
                 status="member", joined=False):
        key = (chat_id, user_id)
        previous = self._membership_events.get(key)
        user = self.state.users.get(user_id)
        if previous is not None and (at, update_id) < (previous.at, previous.update_id):
            if joined and previous.joined_at is None and user is not None and chat_id in user.chat_ids:
                # An older join can refine a member first observed through a newer message.
                previous.joined_at = at
                self._remember_user(chat_id, user_id, at)
            return
        joined_at = previous.joined_at if previous is not None else None
        same_join = joined_at is not None and abs(joined_at - at) <= 1
        self._membership_events[key] = MembershipEvent(at, update_id, at if joined else joined_at)
        if not active:
            self._mark_not_present(chat_id, user_id, status, "membership_update")
            return
        since = at if joined else time.time()
        if user is None:
            self._remember_user(chat_id, user_id, since)
        elif chat_id not in user.chat_ids:
            user.chat_ids.append(chat_id)
            self._membership_changed(user_id, user)
            self._remember_user(chat_id, user_id, since)
            self._changed()
        elif joined and not same_join:
            self._membership_changed(user_id, user)
            self._remember_user(chat_id, user_id, since)
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
            own_user = self._remember_user(chat.id, self.bot.id, time.time())
            if chat.id not in own_user.chat_ids:
                own_user.chat_ids.append(chat.id)
                self._membership_changed(self.bot.id, own_user)
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
                    self._observe(chat.id, message.from_user.id, at, update.update_id)
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
        for (chat_id, user_id), event in list(self._membership_events.items()):
            if chat_id == old_id:
                del self._membership_events[(chat_id, user_id)]
                previous = self._membership_events.get((new_id, user_id))
                if previous is None or (event.at, event.update_id) > (previous.at, previous.update_id):
                    self._membership_events[(new_id, user_id)] = event
        for user in self.state.users.values():
            user.chat_ids = list(dict.fromkeys(new_id if chat_id == old_id else chat_id for chat_id in user.chat_ids))
        for job in self.state.queue.values():
            if job.chat_id == old_id:
                job.chat_id = new_id
        for entry in self.state.removals:
            if entry.chat_id == old_id:
                entry.chat_id = new_id
        for user in self.state.users.values():
            if user.first_chat_id == old_id:
                user.first_chat_id = new_id
        for candidate in self.state.protection.quarantine.values():
            if old_id in candidate.targets:
                candidate.targets = list(dict.fromkeys(new_id if chat_id == old_id else chat_id
                                                      for chat_id in candidate.targets))
        for reservation in self.state.protection.reservations:
            if reservation.chat_id == old_id:
                reservation.chat_id = new_id
        self.state.protection.populations_at = 0
        if self.config.reference_chat_id == old_id:
            config = self.config.model_copy(update={"reference_chat_id": new_id})
            await self._save_config(config)
        self.state.moderated_chats = sorted(self.moderated_chat_ids())
        self._generation += 1
        self._changed()
        await self.save()

    def _enqueue(self, user_id, source="scheduled") -> bool:
        user = self.state.users.get(user_id)
        key = str(user_id)
        if user is None or not self._moderated_chats_for(user) or key in self.state.queue:
            return False
        self.state.queue[key] = CheckJob(
            user_id=user_id, generation=user.generation,
            enqueued_at=time.time(), source=source,
        )
        self._changed()
        return True

    def _remember_member(self, chat_id, member):
        if self.bot_state.is_chat_moderated(chat_id) and is_present(member):
            user = self._remember_user(chat_id, member.user.id, time.time())
            if chat_id not in user.chat_ids:
                user.chat_ids.append(chat_id)
                self._membership_changed(member.user.id, user)

    async def enqueue_grade(self, grade):
        if self.state.status != "running":
            return 0, 0
        added = existing = 0
        now = time.time()
        for user_id in self.state.users:
            if user_id == self.bot.id or not self._moderated_chats_for(self.state.users[user_id]):
                continue
            if grade != "ALL" and self._user_grade(user_id, now).name != grade:
                continue
            if self._enqueue(user_id, "manual"):
                added += 1
            else:
                existing += 1
        await self.save()
        return added, existing

    async def _maintenance(self, context):
        try:
            self._sync_chats()
            self.bot_state.prune_message_edit_histories()
            now = time.time()
            self._refresh_grades(now)
            self._recent_errors(now)
            self.protection.tick(now)
            self.protection.schedule_notifications()
            horizon = max(self.HISTORY_TTL, self.config.protection.removal_statistics_days * 86400)
            history = [entry for entry in self.state.removals if entry.removed_at > now - horizon]
            if len(history) != len(self.state.removals):
                self.state.removals = history
                self._changed()
            if self.state.status == "running":
                for user_id, user in self.state.users.items():
                    if user_id == self.bot.id or not self._moderated_chats_for(user):
                        continue
                    grade = self._user_grade(user_id, now)
                    if user.last_successful_check is not None and user.next_check_at <= 0:
                        user.next_check_at = user.last_successful_check + self._check_interval(grade)
                        self._changed()
                    if user.next_check_at <= now:
                        self._enqueue(user_id)
            await self.save()
        except Exception as error:
            self._error(None, "maintenance", "worker_error", detail=error)

    def _guard(self, generation, job=None, *, running=True):
        if generation != self._generation or not self._storage_healthy or not self._config_healthy:
            raise CoronerInterrupted()
        if running and self.state.status != "running":
            raise CoronerInterrupted()
        if job is not None:
            user = self.state.users.get(job.user_id)
            if (user is None or not self._moderated_chats_for(user) or user.generation != job.generation
                    or self.state.queue.get(job.key) is not job):
                raise CoronerInterrupted()
            if job.chat_id is not None and (job.chat_id not in user.chat_ids
                    or not self.bot_state.is_chat_moderated(job.chat_id)):
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
            # chat_id is the previous attempt's context, not the identity of this global job.
            if job.chat_id is not None:
                if not self.bot_state.is_chat_moderated(job.chat_id):
                    self.logger.info("CORONER reset obsolete check context for user %s: chat %s is not moderated",
                                     job.user_id, job.chat_id)
                job.chat_id = None
                self._changed()
            delay = 0.01
            try:
                self._guard(generation, job)
                await self._process_job(job, generation)
            except CoronerInterrupted:
                # Keep valid jobs on stop; discard obsolete joins or abandoned chats.
                user = self.state.users.get(job.user_id)
                if (user is None or not self._moderated_chats_for(user)
                        or user.generation != job.generation):
                    self._finish_job(job)
                elif job.chat_id not in user.chat_ids:
                    job.chat_id = None
                    self._changed()
            except ChatMigrated as error:
                await self.migrate_chat(job.chat_id, error.new_chat_id)
            except Exception as error:
                if self.state.queue.get(job.key) is job:
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

    def _complete_check(self, job, user):
        user.last_successful_check = time.time()
        grade = self._user_grade(job.user_id, user.last_successful_check)
        user.next_check_at = user.last_successful_check + self._check_interval(grade)
        self._finish_job(job)
        self._changed()

    def _check_interval(self, grade):
        maximum = grade.max_check_interval_seconds
        minimum = max(1, math.ceil(maximum * self.config.min_check_inverval_precent / 100))
        return random.randint(minimum, maximum)

    async def _process_job(self, job, generation):
        while job.user_id in self.state.users:
            try:
                if await self._check_user(job, generation) is not False:
                    return
            except BadRequest as error:
                self._guard(generation, job)
                if job.user_id == self.config.reference_user_id or not CoronerApi.is_missing_member(error):
                    raise
                self._mark_not_present(job.chat_id, job.user_id, "not_found", str(error))
                job.chat_id = None
                if not await self.save(force=True):
                    raise CoronerInterrupted()

    async def _check_user(self, job, generation):
        user = self.state.users[job.user_id]
        last_alive_at = user.last_alive_at

        def guard():
            self._guard(generation, job)
            if user.last_alive_at != last_alive_at:
                raise CoronerInterrupted()

        if self.state.checks_since_reference >= self.config.reference_check_every:
            job.chat_id = None
            if await self._check_reference(generation) is not True:
                return
        guard()
        job.chat_id = random.choice(self._moderated_chats_for(user))
        self._changed()
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
        if job.user_id == self.config.reference_user_id:
            if await self._check_reference(generation) is True:
                self._complete_check(job, user)
            return
        if not is_present(member):
            self._mark_not_present(job.chat_id, job.user_id, member.status, "get_chat_member")
            job.chat_id = None
            if not await self.save(force=True):
                raise CoronerInterrupted()
            return False  # Continue this global job in another chat without a retry delay.
        alive = is_alive(member.user, job.user_id)
        self.protection.record_check(job.user_id, job.chat_id, alive)
        if alive is True:
            self._complete_check(job, user)
            return
        if alive is False:
            profile = await self.api.call(
                self.bot.get_chat, chat_id=job.user_id, error_chat_id=job.chat_id,
                background=True, priority=10, guard=guard,
            )
            alive = is_alive(profile, job.user_id)
            guard()
            if alive is True:
                user.last_alive_at = time.time()
                self.protection.cancel_candidate(job.user_id)
        if alive is not False:
            self.protection.record_check(job.user_id, job.chat_id, None, primary=False)
            self._error(job.chat_id, f"profile:{job.user_id}", "profile_unknown", user_id=job.user_id)
            job.not_before = time.time() + self.config.retry_delay_seconds
            self._changed()
            return
        if member.status in ("administrator", "creator"):
            self._error(job.chat_id, f"protected:{job.user_id}", "protected_member", user_id=job.user_id)
            self._complete_check(job, user)
            return
        candidate = self.protection.enter(job, user)
        if candidate is None:
            self._complete_check(job, user)
            return
        retry_at = 0
        for chat_id in list(candidate.targets):
            if chat_id not in self._moderated_chats_for(user):
                self.protection.finish_target(job.user_id, chat_id)
                continue
            job.chat_id = chat_id
            if not self.protection.permitted(candidate, chat_id, user.generation):
                job.not_before = max(time.time() + 1, min(candidate.ready_at,
                                      time.time() + self.config.protection.recheck_seconds))
                if candidate.ready_at <= time.time():
                    job.not_before = time.time() + self.config.protection.recheck_seconds
                job.not_before = max(job.not_before, retry_at)
                self._changed()
                return
            last_alive_at = user.last_alive_at
            try:
                await self.cremate(job, user, generation)
            except (ChatMigrated, RetryAfter):
                raise
            except TelegramError as error:
                self._guard(generation, job)
                if user.last_alive_at != last_alive_at:
                    raise CoronerInterrupted()
                if CoronerApi.is_missing_member(error):
                    self._mark_not_present(chat_id, job.user_id, "not_found", str(error))
                else:
                    job.attempts += 1
                    retry_at = max(retry_at, time.time() + self.api.retry_delay(error, self.config.retry_delay_seconds))
                    # A failed target must not starve the remaining chats in this user's job.
                    if chat_id in candidate.targets:
                        candidate.targets.remove(chat_id)
                        candidate.targets.append(chat_id)
                job.chat_id = None
                self._changed()
                if not await self.save(force=True):
                    raise CoronerInterrupted()
                if job.user_id not in self.state.users or not self._moderated_chats_for(user):
                    return
                continue
            if job.user_id not in self.state.users or not self._moderated_chats_for(user):
                return
            if chat_id in candidate.targets:
                job.not_before = max(job.not_before, retry_at)
                self._changed()
                return  # A budget/reference/resource failure left this target pending.
        if candidate.targets:
            job.not_before = retry_at
            self._changed()
            return
        self._complete_check(job, user)

    async def cremate(self, job: CheckJob, user: TrackedUser, generation: int):
        if job.user_id in (self.bot.id, self.config.reference_user_id):
            raise CoronerInterrupted()
        candidate = self.state.protection.quarantine.get(job.user_id)
        if candidate is None or not self.protection.permitted(candidate, job.chat_id, user.generation):
            raise CoronerInterrupted()
        if await self._check_reference(generation) is not True:
            return
        def guard():
            self._guard(generation, job)
            if (not self.protection.permitted(candidate, job.chat_id, user.generation)
                    or event_version != user.generation
                    or last_alive_at != self.state.users[job.user_id].last_alive_at):
                raise CoronerInterrupted()
        event_version = user.generation
        last_alive_at = self.state.users[job.user_id].last_alive_at
        # Re-read membership after confirmation and the reference check;
        # skip existing bans and protect administrators.
        try:
            member = await self.api.call(
                self.bot.get_chat_member, chat_id=job.chat_id, user_id=job.user_id,
                error_chat_id=job.chat_id, background=True, priority=10, guard=guard,
            )
        except BadRequest as error:
            guard()
            if not CoronerApi.is_missing_member(error):
                raise
            self._mark_not_present(job.chat_id, job.user_id, "not_found", str(error))
            job.chat_id = None
            return
        guard()
        if event_version != user.generation:
            raise CoronerInterrupted()
        if not is_present(member):
            self._mark_not_present(job.chat_id, job.user_id, member.status, "pre-ban membership check")
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
            return
        grade = self._user_grade(job.user_id, time.time()).name
        reservation = None
        def removal_guard():
            guard()
            if job.chat_id not in user.chat_ids or event_version != user.generation:
                raise CoronerInterrupted()
            if reservation is not None:
                failure = self.protection.budget_failure(
                    job.chat_id, self.state.protection.populations, reservation=reservation,
                )
                if failure is not None:
                    self.protection.trip(failure)
                    raise CoronerInterrupted()

        reservation = await self.protection.reserve(job, removal_guard)
        if reservation is None:
            job.not_before = time.time() + self.config.protection.recheck_seconds
            self._changed()
            return
        dispatched = False

        @wraps(self.bot.ban_chat_member)
        async def remove(**params):
            nonlocal dispatched
            dispatched = True
            return await self.bot.ban_chat_member(**params)

        try:
            if self.config.dry_run:
                removal_guard()
                reservation.state = "completed"
                self.logger.info("CORONER dry_run: would permanently ban user %s from chat %s; grade=%s source=%s operation=%s",
                                 job.user_id, job.chat_id, grade, job.source, reservation.id)
                self.protection.finish_target(job.user_id, job.chat_id)
                return
            self._changed()
            if not await self.save(force=True):
                raise CoronerInterrupted()

            # The fresh membership check excludes existing bans; the guard
            # catches received membership events before the request is sent.
            result = await self.api.call(
                remove, chat_id=job.chat_id, user_id=job.user_id,
                until_date=0, error_chat_id=job.chat_id, background=True,
                priority=10, guard=removal_guard,
            )
            if result is not True:
                raise RuntimeError("Telegram did not confirm removal")
            reservation.state = "completed"
            reservation.at = time.time()
        except (BadRequest, Forbidden):
            reservation.state = "released"
            raise
        except Exception:
            reservation.state = "uncertain" if dispatched else "released"
            if dispatched:
                reservation.at = time.time()
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
        self._mark_not_present(job.chat_id, job.user_id, "kicked", "coroner_ban")
        job.chat_id = None
        self._changed()
        await self.save(force=True)
        self.logger.info("CORONER permanently banned user %s from chat %s; grade=%s operation=%s",
                         job.user_id, reservation.chat_id, grade, reservation.id)

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

        targets = self.moderated_chat_ids()
        lookup_chats = sorted(targets) if targets else [chat_id]
        for target in lookup_chats:
            if not await self.bot_state.is_admin(user_id, target, telegram_request=telegram_request):
                return False
        return targets == self.moderated_chat_ids()

    async def status_text(self, locale):
        t = lambda key, **values: coroner_text(locale, key, **values)
        chat_ids = self.moderated_chat_ids()
        totals = {}
        for chat_id in sorted(chat_ids):
            try:
                totals[chat_id] = await self.api.call(
                    self.bot.get_chat_member_count, chat_id=chat_id, error_chat_id=chat_id,
                )
            except Exception:
                pass
        now = time.time()
        self.protection.evaluate(now)
        monitored = set()
        observed_total = member_total = 0
        complete_counts = bool(chat_ids)
        chat_untracked = []
        for chat_id in sorted(chat_ids):
            active = {user_id for user_id, user in self.state.users.items() if chat_id in user.chat_ids}
            # Telegram counts memberships, including this bot, separately in each chat.
            observed = len(set(active) | {self.bot.id})
            total = totals.get(chat_id)
            value = t("unavailable")
            if type(total) is not int or total <= 0:
                complete_counts = False
            else:
                # Saved memberships can outlive a departure. Coverage is an estimate,
                # so cap it per chat instead of treating stale links as an API failure.
                observed = min(observed, total)
                member_total += total
                observed_total += observed
                value = f"{100 * (total - observed) / total:.2f}%"
            chat_untracked.append(t("untracked_chat", chat=self.chat_label(chat_id), value=value))
            monitored.update(user_id for user_id in active if user_id != self.bot.id)
        untracked = (f"{100 * (member_total - observed_total) / member_total:.2f}%"
                     if complete_counts else t("unavailable"))
        jobs = [job for job in self.state.queue.values()
                if job.user_id in monitored and job.user_id not in self.state.protection.quarantine]
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
        lines.append(t("protection_status", status=t("protection_blocked" if self.protection.is_blocked() else "protection_clear")))
        lines.append(self.protection.bypass_status(t))
        lines.append(self.protection.approval_status(t))
        lines.append(t("quarantine_count", count=len(protection.quarantine)))
        if self.protection.is_blocked():
            for signal in self.protection.blocking_reasons()[-2:]:
                lines.append(shorten(self.protection.reason_text(signal), 220))
        if self.config.reference_user_id is None:
            lines.append(t("reference_missing"))
        else:
            lines.append(t("reference", user_id=self.config.reference_user_id,
                           chat_id=self.chat_label(self.config.reference_chat_id), every=self.config.reference_check_every))
        if self.state.last_reference_at is None:
            lines.append(t("reference_never"))
        else:
            result = {True: "alive", False: "deleted", None: "unknown"}[self.state.last_reference_alive]
            lines.append(t("reference_last", result=t(result), age=duration(now - self.state.last_reference_at)))
        if self._reference_pending:
            lines.append(t("reference_waiting"))
        lines.extend(["", t("monitored", count=len(monitored)), t("untracked", value=untracked)])
        lines.extend(chat_untracked)
        lines.append("")
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
        return "\n".join(lines)
