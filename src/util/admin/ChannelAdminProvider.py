from logging import Logger

from telegram import Update, Bot
from telegram.ext import CallbackContext, Application

from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.admin.AdminProvider import AdminProvider


class ChannelAdminProvider(AdminProvider):
    """Provides a list of admin users"""


    def __init__(self, logger: Logger, bot: Bot):
        self.logger = logger
        self.bot = bot

    async def is_admin(self, user_id: int, chat_id:int) -> bool:
        chat_admins = await self.bot.get_chat_administrators(chat_id)
        if user_id in [admin.user.id for admin in chat_admins]:
            return True
        return False



