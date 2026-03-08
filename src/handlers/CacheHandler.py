from telegram import Chat, TelegramObject, User
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.data.BotState import CachedChannel, CachedUser


class CacheHandler(BaseHandler):
    async def handle_update(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        users_by_id: dict[int, User] = {}
        chats_by_id: dict[int, Chat] = {}
        self._collect_entities(update, users_by_id, chats_by_id, set())
        self._upsert_users(users_by_id)
        self._upsert_chats(chats_by_id)

    def _collect_entities(self, value, users_by_id: dict[int, User], chats_by_id: dict[int, Chat],
                          visited: set[int]) -> None:
        if value is None:
            return
        if isinstance(value, (str, int, float, bool, bytes)):
            return

        value_id = id(value)
        if value_id in visited:
            return
        visited.add(value_id)

        if isinstance(value, User):
            users_by_id[value.id] = value
            return

        if isinstance(value, Chat):
            chats_by_id[value.id] = value
            return

        if isinstance(value, dict):
            for item in value.values():
                self._collect_entities(item, users_by_id, chats_by_id, visited)
            return

        if isinstance(value, (list, tuple, set)):
            for item in value:
                self._collect_entities(item, users_by_id, chats_by_id, visited)
            return

        if isinstance(value, TelegramObject):
            fields = getattr(value, "__slots__", ())
            for field in fields:
                if field.startswith("_"):
                    continue
                self._collect_entities(getattr(value, field, None), users_by_id, chats_by_id, visited)

    def _upsert_users(self, users_by_id: dict[int, User]) -> None:
        for user in users_by_id.values():
            cached_user = CachedUser(
                id=user.id,
                first_name=user.first_name,
                username=user.username,
                last_name=user.last_name
            )
            if self.state.get_cached_user(user.id) != cached_user:
                self.state.set_cached_user(cached_user)

    def _upsert_chats(self, chats_by_id: dict[int, Chat]) -> None:
        for chat in chats_by_id.values():
            if self.state.get_cached_channel(chat.id) is None:
                self.state.set_cached_channel(CachedChannel(id=chat.id))
