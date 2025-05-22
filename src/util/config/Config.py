from typing import Optional

from pydantic import BaseModel

from src.util.admin.AdminProvider import AdminProvider
from src.util.config.ModelRepo import ModelRepo


class Config(BaseModel):
    trusted_user_ids: list[int] = []
    banned_channel_ids: list[int] = []
    moderated_chat_ids: list[int] = []
    audit_log_chat_id: Optional[int] = None
    __config_repo: ModelRepo = None
    __admin_provider: AdminProvider = None

    @classmethod
    def load_from_file(cls, admin_provider: AdminProvider, config_repo: ModelRepo['Config']) -> 'Config':
        config = config_repo.load(Config, Config())
        config.__admin_provider = admin_provider
        config.__config_repo = config_repo
        return config

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
        self.__config_repo.save(self)

    def stop_chat_moderating(self, chat_id: int):
        """
        Disable chat moderation.
        :param chat_id: Chat id.
        """
        self.moderated_chat_ids.remove(chat_id)
        self.__config_repo.save(self)

    def set_audit_log_chat(self, chat_id: int):
        """
        Set chat as audit log chat.
        :param chat_id: Chat id.
        """
        self.audit_log_chat_id = chat_id
        self.__config_repo.save(self)

    def remove_audit_log_chat(self):
        """
        Remove audit log chat.
        """
        self.audit_log_chat_id = None
        self.__config_repo.save(self)

    def is_channel_banned(self, community_id: int) -> bool:
        """
        Check if community is banned.
        """
        return community_id in self.banned_channel_ids

    def ban_channel(self, community_id: int):
        """
        Ban community.
        """
        if community_id >= 0:
            community_id = int(f"-100{community_id}")
        self.banned_channel_ids.append(community_id)
        self.__config_repo.save(self)

    def get_audit_log_chat_id(self) -> Optional[int]:
        """
        Get audit log chat id.
        :return: Audit log chat id.
        """
        return self.audit_log_chat_id

    def trust(self, user_id: int):
        """
        Add user to trusted users list (trusted users are not checked for spam).
        :param user_id: User id.
        """
        self.trusted_user_ids.append(user_id)
        self.__config_repo.save(self)

    def distrust(self, user_id: int):
        """
        Remove user from trusted users list.
        :param user_id: User id.
        """
        self.trusted_user_ids.remove(user_id)
        self.__config_repo.save(self)

    def is_user_trusted(self, user_id: int) -> bool:
        """
        Check if user is trusted.
        :param user_id: User id.
        """
        return user_id in self.trusted_user_ids

    async def is_admin(self, user_id: int, chat_id: int) -> bool:
        """
        Check if user is admin.
        :param user_id: User id.
        :param chat_id: Chat id.
        """
        return await self.__admin_provider.is_admin(user_id, chat_id)
