from functools import wraps

from telegram import Update, User, Chat
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
        chat: Chat = update.effective_chat
        if not await self.config.is_admin(user.id, chat.id):
            self.logger.info(f"Unauthorized access attempt by user {user.id}")
            return
        return await func(self, update, context, *args, **kwargs)

    return wrapper

def get_argument_value(update: Update, index: int) -> str | None:
    """
    Extracts the argument value from the command message.
    """
    if update.message is None or update.message.text is None:
        return None
    args = update.message.text.split(" ")
    if len(args) > index:
        return args[index]
    return None

def get_int_argument_value(update: Update, index: int) -> int | None:
    """
    Extracts the integer argument value from the command message.
    """
    arg_value = get_argument_value(update, index)
    if arg_value is not None and arg_value.isdigit():
        return int(arg_value)
    return None


class BaseHandler:
    __logger_name = "GenericHandler"

    def __init__(self, config: Config):
        self.config = config
        self.logger = LoggerUtil.get_logger("EventHandler", self.__logger_name)
        self.telegram_helper = TelegramHelper(self.logger, config)
