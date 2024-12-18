from functools import wraps

from telegram import Update, User
from telegram.ext import CallbackContext

from src.TelegramHelper import TelegramHelper
from src.util.LoggerUtil import LoggerUtil
from src.util.config.Config import Config


def admin_command(func):
    """
    Decorator to ensure that a command is only executed by an admin user.
    """
    @wraps(func)
    async def wrapper(self, update: Update, context: CallbackContext, *args, **kwargs):
        user: User = update.effective_user
        if not self.config.is_admin(user.id):
            self.logger.info(f"Unauthorized access attempt by user {user.id}")
            return
        return await func(self, update, context, *args, **kwargs)
    return wrapper

class BaseHandler:

    __logger_name = "GenericHandler"

    def __init__(self, config: Config):
        self.config = config
        self.logger = LoggerUtil.get_logger("EventHandler", self.__logger_name)
        self.telegram_helper = TelegramHelper(self.logger, config)

