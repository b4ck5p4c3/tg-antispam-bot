import time
from threading import Timer
from typing import Dict, Optional
from venv import logger

from telegram import Update, MessageOriginChannel, MessageOrigin, MessageOriginChat
from telegram.ext import CallbackContext

from src.handlers.spam_filters.HTTPJsonSpamFilter import HTTPJsonSpamFilter
from src.util.config.Config import Config


def get_channel_id(origin: MessageOrigin) -> Optional[int]:
    if origin is None:
        return None
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.id
    elif isinstance(origin, MessageOriginChat):
        return origin.sender_chat.id
    else:
        return None

def get_forward_channel_id(update: Update) -> Optional[int]:
    forward_origin = update.message.forward_origin
    return get_channel_id(forward_origin)

class ForwardSpamFilter(HTTPJsonSpamFilter):

    def __init__(self, config: Config):
        super().__init__(config)


    async def _is_spam(self, update: Update, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        channel_id = get_forward_channel_id(update)
        if channel_id:
            is_banned = self.config.is_channel_banned(channel_id)
            if is_banned:
                self.logger.info(f"Message from banned channel {channel_id} detected")
                return True
            else:
                self.logger.info(f"Message from channel {channel_id} is not banned")
        return False


