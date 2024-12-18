from telegram import Update
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler
from src.handlers.spam_filters.lols.LolsSpamFilter import LolsSpamFilter
from src.util.config.Config import Config


class LolsOnJoinSpamCheck(BaseHandler):
    def __init__(self, config: Config, lols_spam_filter: LolsSpamFilter):
        super().__init__(config)
        self.lols_spam_filter = lols_spam_filter


    async def handle_user_join(self, update: Update, context: CallbackContext) -> None:
        """Handles the user join event."""
        for user in update.message.new_chat_members:
            if self.lols_spam_filter.is_spam(user.id):
                await self.telegram_helper.ban_message_author(context, user.id, update.message)