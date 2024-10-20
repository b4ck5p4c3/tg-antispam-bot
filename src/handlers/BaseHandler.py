from functools import wraps
from logging import Logger

from telegram import Update, User
from telegram.ext import CallbackContext

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

    def __init__(self, logger: Logger, config: Config):
        self.logger = logger
        self.config = config

