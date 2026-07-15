from telegram.ext import CallbackContext

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.telegram.EnrichedUpdate import EnrichedUpdate


class ChannelSpamFilter(SpamFilter):
    _filter_name = "ChannelSender"

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        if update.message.is_automatic_forward:
            return False

        sender_chat = self.telegram_helper.extract_message_sender_chat(update.message)
        if sender_chat is None:
            return False
        self.logger.info(f"Message {update.message.id} was sent by channel {sender_chat.id}, treating as spam")
        return True
