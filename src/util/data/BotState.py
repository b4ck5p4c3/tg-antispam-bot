from typing import Optional

from pydantic import BaseModel

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
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class CachedChannel(BaseModel):
    id: int




class BotState(BaseModel):
    trusted_user_ids: list[int] = []
    banned_channel_ids: list[int] = []
    moderated_chat_ids: list[int] = []
    event_subscriber_id: dict[BotEvent, list[int]] = {}
    audit_log_chat_id: Optional[int] = None
    user_cache: dict[int, CachedUser] = {}
    channel_cache: dict[int, CachedChannel] = {}
    __state_repo: ModelRepo = None
    __admin_provider: AdminProvider = None

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
        Add user to trusted users list (trusted users are not being checked for spam).
        :param user_id: User id.
        """
        self.trusted_user_ids.append(user_id)
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

    async def is_admin(self, user_id: int, chat_id: int) -> bool:
        """
        Check if user is admin.
        :param user_id: User id.
        :param chat_id: Chat id.
        """
        return await self.__admin_provider.is_admin(user_id, chat_id)
