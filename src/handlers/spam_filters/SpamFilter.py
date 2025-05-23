from typing import Optional

from telegram import Message
from telegram.ext import CallbackContext

from src.TelegramHelper import TelegramHelper
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.LoggerUtil import LoggerUtil
from src.util.config.Config import Config


def extract_message_text(update: EnrichedUpdate) -> Optional[str]:
    if update.message is None:
        return None
    if update.message.text is not None:
        return update.message.text
    elif update.message.caption is not None:
        return update.message.caption
    return None


class SpamFilter:
    _filter_name = "Generic Filter"
    __logger_name = "SpamFilter"
    __ignored_message_types = [
        Message.left_chat_member, Message.new_chat_members
    ]

    def __init__(self, config: Config, next_filter: Optional['SpamFilter'] = None):
        self.config = config
        self.logger = LoggerUtil.get_logger(self.__logger_name, self._filter_name)
        self.next_filter = next_filter
        self.telegram_helper = TelegramHelper(self.logger, config)

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns True if message is spam, otherwise False."""
        # Implement the spam checking logic here
        raise NotImplementedError("Subclasses should implement this method.")

    async def _on_spam(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Bans the user if the message is identified as spam."""
        user_id = update.message.from_user.id
        self.logger.warning(f"Banning user {user_id} for sending spam")
        await self.telegram_helper.try_remove_message(context, update.message)
        await self.telegram_helper.ban_message_author(context, update.message)

    async def _is_message_should_be_ignored(self, update: EnrichedUpdate) -> bool:
        """Checks if the message should be ignored."""

        if update.message is None:
            self.logger.debug("Update is not a message, skipping spam check")
            return True
        conditions = [
            (self.__is_message_type_not_supported(update.message),
            f"Message {update.message.id} type is blacklisted, skipping spam check"),
            (self.config.is_user_trusted(update.message.from_user.id),
             f"User {update.message.from_user.id} is trusted, skipping spam check"),
            (not self.config.is_chat_moderated(update.message.chat_id),
             f"Chat {update.message.chat_id} is not moderated, skipping spam check"),
            (await self.config.is_admin(update.effective_user.id, update.effective_chat.id),
             f"User {update.message.from_user.id} is admin, skipping spam check"),
        ]

        for condition, message in conditions:
            if condition:
                self.logger.debug(f"{message}")
                return True
        return False

    @staticmethod
    def __is_message_type_not_supported(message: Message) -> bool:
        return message.left_chat_member is not None or len(message.new_chat_members)!=0

    async def _on_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Adds the user to the trusted list if the message is not spam."""
        self.logger.info(f"Message from user {update.message.from_user.id} is not spam")

    async def __on_filter_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Executed when the message passes all filters successfully."""
        self.logger.debug(f"Message from user {update.message.from_user.id} passed all filters, trusting user..")
        self.config.trust(update.message.from_user.id)

    from typing import final

    @final
    async def apply(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Applies the spam filter to the incoming message."""
        if await self._is_message_should_be_ignored(update):
            return
        if await self._is_spam(update, context):
            await self._on_spam(update, context)
            return
        else:
            await self._on_pass(update, context)

        if self.next_filter:
            await self.next_filter.apply(update, context)
        else:
            await self.__on_filter_pass(update, context)
