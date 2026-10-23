from collections.abc import Callable
from typing import Literal, Optional

from pydantic import AliasChoices, BaseModel, Field

from src.util.admin.AdminProvider import AdminProvider
from src.util.data.BotEvent import BotEvent
from src.util.data.ModelRepo import ModelRepo


def get_community_id(community_id: int) -> int:
    """
    Get community id from channel id.
    :param community_id: Channel id.
    :return: Community id.
    """
    if community_id > 0:
        community_id = int(f"-100{community_id}")
    return community_id


class CachedUser(BaseModel):
    id: int
    first_name: str
    username: Optional[str] = None
    last_name: Optional[str] = None


class CachedChannel(BaseModel):
    id: int
    title: Optional[str] = None


class MessageRevision(BaseModel):
    target_message: str
    attachment_transcript: str = ""
    replied_to_message: str = ""


class MessageEditCounter(BaseModel):
    message_id: int
    edit_count: int = 0
    last_update_id: int = -1


class MessageEditHistory(MessageEditCounter):
    revisions: list[MessageRevision] = Field(default_factory=list)


class AuditLogBan(BaseModel):
    user_id: int
    banned_chat_id: int


class UnbanChat(BaseModel):
    title: str
    status: Literal["pending", "unbanned", "not_banned"] = "pending"
    error: Optional[str] = None


class UnbanRequest(BaseModel):
    user_id: int
    expected_username: Optional[str] = None
    chats: dict[int, UnbanChat] = Field(default_factory=dict)
    scan_errors: dict[int, str] = Field(default_factory=dict)


class BotState(BaseModel):
    trusted_user_ids: list[int] = []
    banned_channel_ids: list[int] = []
    moderated_chat_ids: list[int] = []
    event_subscriber_id: dict[BotEvent, list[int]] = {}
    audit_log_chat_id: Optional[int] = None
    user_cache: dict[int, CachedUser] = {}
    channel_cache: dict[int, CachedChannel] = {}
    audit_log_registry: dict[int, dict[int, AuditLogBan]] = Field(default_factory=dict)
    unban_requests: dict[int, dict[int, UnbanRequest]] = Field(default_factory=dict)
    message_edit_histories: dict[int, dict[int, MessageEditHistory]] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("message_edit_histories", "first_message_histories"),
    )
    message_edit_counters: dict[int, dict[int, MessageEditCounter]] = Field(default_factory=dict)
    __state_repo: ModelRepo = None
    __admin_provider: AdminProvider = None
    __history_tracking: Callable[[int, int], bool] | None = None

    @classmethod
    def load_from_file(cls, admin_provider: AdminProvider, state_repo: ModelRepo['BotState']) -> 'BotState':
        state = state_repo.load(BotState, BotState())
        state.__admin_provider = admin_provider
        state.__state_repo = state_repo
        return state

    def is_chat_moderated(self, chat_id: int) -> bool:
        """
        Check if chat is moderated.
        :param chat_id: Chat id.
        :return: True if chat is moderated, False otherwise.
        """
        return chat_id in self.moderated_chat_ids

    def moderate_chat(self, chat_id: int):
        """
        Enable chat moderation.
        :param chat_id: Chat id.
        """
        self.moderated_chat_ids.append(chat_id)
        self.__state_repo.save(self)

    def stop_chat_moderating(self, chat_id: int):
        """
        Disable chat moderation.
        :param chat_id: Chat id.
        """
        self.moderated_chat_ids.remove(chat_id)
        self.message_edit_histories.pop(chat_id, None)
        self.message_edit_counters.pop(chat_id, None)
        self.__state_repo.save(self)

    def migrate_moderated_chat(self, old_id: int, new_id: int) -> None:
        if old_id not in self.moderated_chat_ids:
            return
        self.moderated_chat_ids = list(dict.fromkeys(
            new_id if chat_id == old_id else chat_id for chat_id in self.moderated_chat_ids
        ))
        histories = self.message_edit_histories.pop(old_id, {})
        self.message_edit_histories.setdefault(new_id, {}).update(histories)
        counters = self.message_edit_counters.pop(old_id, {})
        self.message_edit_counters.setdefault(new_id, {}).update(counters)
        self.__state_repo.save(self)

    def set_audit_log_chat(self, chat_id: int):
        """
        Set chat as audit log chat.
        :param chat_id: Chat id.
        """
        self.audit_log_chat_id = chat_id
        self.__state_repo.save(self)

    def remove_audit_log_chat(self):
        """
        Remove audit log chat.
        """
        self.audit_log_chat_id = None
        self.__state_repo.save(self)

    def is_channel_banned(self, community_id: int) -> bool:
        """
        Check if community is banned.
        """
        return get_community_id(community_id) in self.banned_channel_ids

    def ban_channel(self, community_id: int):
        """
        Ban community.
        """
        self.banned_channel_ids.append(get_community_id(community_id))
        self.__state_repo.save(self)

    def get_audit_log_chat_id(self) -> Optional[int]:
        """
        Get audit log chat id.
        :return: Audit log chat id.
        """
        return self.audit_log_chat_id

    def get_cached_user(self, user_id: int) -> Optional[CachedUser]:
        """
        Get cached user by id.
        :param user_id: User id.
        :return: Cached user or None.
        """
        return self.user_cache.get(user_id)

    def get_cached_user_by_username(self, username: str) -> Optional[CachedUser]:
        username = username.removeprefix("@").casefold()
        matches = [
            user for user in self.user_cache.values()
            if user.username is not None and user.username.casefold() == username
        ]
        return matches[0] if len(matches) == 1 else None

    def register_audit_log_ban(self, chat_id: int, message_id: int, ban: AuditLogBan) -> None:
        self.audit_log_registry.setdefault(chat_id, {})[message_id] = ban
        self.__state_repo.save(self)

    def get_audit_log_ban(self, chat_id: int, message_id: int) -> Optional[AuditLogBan]:
        return self.audit_log_registry.get(chat_id, {}).get(message_id)

    def save_unban_request(self, chat_id: int, message_id: int, request: UnbanRequest) -> None:
        self.unban_requests.setdefault(chat_id, {})[message_id] = request
        self.__state_repo.save(self)

    def get_unban_request(self, chat_id: int, message_id: int) -> Optional[UnbanRequest]:
        return self.unban_requests.get(chat_id, {}).get(message_id)

    def set_cached_user(self, user: CachedUser) -> None:
        """
        Save single cached user.
        :param user: Cached user.
        """
        self.user_cache[user.id] = user
        self.__state_repo.save(self)

    def get_cached_channel(self, channel_id: int) -> Optional[CachedChannel]:
        """
        Get cached channel by id.
        :param channel_id: Channel id.
        :return: Cached channel or None.
        """
        return self.channel_cache.get(channel_id)

    def set_cached_channel(self, channel: CachedChannel) -> None:
        """
        Save single cached channel.
        :param channel: Cached channel.
        """
        self.channel_cache[channel.id] = channel
        self.__state_repo.save(self)

    def trust(self, user_id: int):
        """
        Trust subsequent messages and discard saved edit context.
        :param user_id: User id.
        """
        changed = self._discard_trusted_context(user_id)
        if user_id not in self.trusted_user_ids:
            self.trusted_user_ids.append(user_id)
            changed = True
        if changed:
            self.__state_repo.save(self)

    def set_message_history_tracking(self, tracked: Callable[[int, int], bool]) -> None:
        self.__history_tracking = tracked
        self.prune_message_edit_histories()

    def _keep_message_history(self, chat_id: int, user_id: int) -> bool:
        return not self.is_user_trusted(user_id) and self._is_message_author_tracked(chat_id, user_id)

    def _is_message_author_tracked(self, chat_id: int, user_id: int) -> bool:
        return self.__history_tracking is None or self.__history_tracking(chat_id, user_id)

    def _discard_trusted_context(self, user_id: int) -> bool:
        for chat_id, histories in self.message_edit_histories.items():
            history = histories.get(user_id)
            if history is not None and self._is_message_author_tracked(chat_id, user_id):
                self.message_edit_counters.setdefault(chat_id, {})[user_id] = MessageEditCounter(
                    message_id=history.message_id, edit_count=history.edit_count,
                    last_update_id=history.last_update_id,
                )
        return self._drop_message_histories(lambda chat, user: user == user_id)

    def _drop_message_histories(self, discard: Callable[[int, int], bool]) -> bool:
        return self._drop_message_records(self.message_edit_histories, discard)

    @staticmethod
    def _drop_message_records(records: dict, discard: Callable[[int, int], bool]) -> bool:
        changed = False
        for chat_id, histories in list(records.items()):
            for user_id in list(histories):
                if discard(chat_id, user_id):
                    del histories[user_id]
                    changed = True
            if not histories:
                del records[chat_id]
                changed = True
        return changed

    def prune_message_edit_histories(self) -> None:
        changed = False
        trusted_with_context = {user for histories in self.message_edit_histories.values()
                                for user in histories if self.is_user_trusted(user)}
        for user_id in trusted_with_context:
            changed = self._discard_trusted_context(user_id) or changed
        changed = self._drop_message_histories(lambda chat, user: not self._keep_message_history(chat, user)) or changed
        changed = self._drop_message_records(
            self.message_edit_counters, lambda chat, user: not self._is_message_author_tracked(chat, user),
        ) or changed
        if changed:
            self.__state_repo.save(self)

    def remove_message_edit_history(self, chat_id: int, user_id: int) -> None:
        discard = lambda chat, user: chat == chat_id and user == user_id
        changed = self._drop_message_histories(discard)
        changed = self._drop_message_records(self.message_edit_counters, discard) or changed
        if changed:
            self.__state_repo.save(self)

    def get_message_edit_history(self, chat_id: int, user_id: int) -> Optional[MessageEditHistory]:
        if not self._is_message_author_tracked(chat_id, user_id):
            return None
        history = self.message_edit_histories.get(chat_id, {}).get(user_id)
        if history is not None and not self.is_user_trusted(user_id):
            return history
        counter = self.message_edit_counters.get(chat_id, {}).get(user_id)
        return MessageEditHistory(**counter.model_dump()) if counter is not None else None

    def save_message_edit_history(self, chat_id: int, user_id: int, history: MessageEditHistory) -> None:
        # An in-flight filter must not recreate context after trust or a membership change.
        if not self._is_message_author_tracked(chat_id, user_id):
            self.remove_message_edit_history(chat_id, user_id)
            return
        if self.is_user_trusted(user_id):
            self._drop_message_histories(lambda chat, user: chat == chat_id and user == user_id)
            self.message_edit_counters.setdefault(chat_id, {})[user_id] = MessageEditCounter(
                message_id=history.message_id, edit_count=history.edit_count,
                last_update_id=history.last_update_id,
            )
            self.__state_repo.save(self)
            return
        self.message_edit_counters.get(chat_id, {}).pop(user_id, None)
        self.message_edit_histories.setdefault(chat_id, {})[user_id] = history
        self.__state_repo.save(self)


    def untrust(self, user_id: int):
        """
        Remove user from trusted users list. -rice
        :param user_id: User id.
        """
        if user_id in self.trusted_user_ids:
            self.trusted_user_ids.remove(user_id)
        self.__state_repo.save(self)

    def distrust(self, user_id: int):
        """
        Remove user from trusted users list.
        :param user_id: User id.
        """
        self.trusted_user_ids.remove(user_id)
        self.__state_repo.save(self)

    def is_user_trusted(self, user_id: int) -> bool:
        """
        Check if user is trusted.
        :param user_id: User id.
        """
        return user_id in self.trusted_user_ids

    def subscribe_event(self, event: BotEvent, user_id: int) -> bool:
        """
        Subscribe user to bot event.
        :param event: Bot event.
        :param user_id: User id.
        :return: True if user was subscribed by this command, False otherwise.
        """
        if event not in self.event_subscriber_id:
            self.event_subscriber_id[event] = []

        if user_id not in self.event_subscriber_id[event]:
            self.event_subscriber_id[event].append(user_id)
            self.__state_repo.save(self)
            return True
        return False


    def unsubscribe_event(self, event: BotEvent, user_id: int) -> bool:
        """
        Unsubscribe user from bot event.
        :param event: Bot event.
        :param user_id: User id.
        :return: True if user was unsubscribed by this command, False otherwise.
        """
        if event not in self.event_subscriber_id:
            return False

        if user_id in self.event_subscriber_id[event]:
            self.event_subscriber_id[event].remove(user_id)
            self.__state_repo.save(self)
            return True
        return False

    def get_event_subscribers(self, event: BotEvent) -> list[int]:
        """
        Get users subscribed to event.
        :param event: Bot event.
        :return: List of user ids.
        """
        return list(self.event_subscriber_id.get(event, []))

    async def is_admin(self, user_id: int, chat_id: int, *, telegram_request=None) -> bool:
        """
        Check if user is admin.
        :param user_id: User id.
        :param chat_id: Chat id.
        """
        if telegram_request is not None:
            return await self.__admin_provider.is_admin_with_request(user_id, chat_id, telegram_request)
        return await self.__admin_provider.is_admin(user_id, chat_id)
