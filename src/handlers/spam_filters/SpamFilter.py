from logging import Logger
from typing import Optional

from telegram import Message
from telegram.ext import CallbackContext

from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.config.Config import Config


class SpamFilter:

    _name = "Generic Filter"

    def __init__(self, logger: Logger, config: Config, next_filter: Optional['SpamFilter'] = None):
        self.config = config
        self.logger = logger
        self.next_filter = next_filter


    def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns True if message is spam, otherwise False."""
        # Implement the spam checking logic here
        raise NotImplementedError("Subclasses should implement this method.")

    async def _on_spam(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Bans the user if the message is identified as spam."""
        user_id = update.message.from_user.id
        self.logger.warning(f"[{self._name}] Banning user {user_id} for sending spam")
        await self._try_remove_message(context, update.message)
        await self._ban_message_author(context, update.message)

    async def _try_remove_message(self, context: CallbackContext, message: Message) -> None:
        try:
            await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
        except Exception as e:
            self.logger.warning(f"[{self._name}] Failed to remove message {message.message_id}: {e}")

    async def _delete_message_with_delay(self, context: CallbackContext, message: Message, delay_seconds: int) -> None:
        self.logger.debug(f"[{self._name}] Deleting message {message.message_id} with delay {delay_seconds}")
        context.job_queue.run_once(lambda ctx: self._try_remove_message(context, message), delay_seconds)

    async def _ban_message_author(self, context: CallbackContext, message: Message) -> None:
        user_id = message.from_user.id
        chat_id = message.chat_id
        self.logger.warning(f"[{self._name}] Banning user {user_id}")
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)

    def _is_message_should_be_ignored(self, update: EnrichedUpdate) -> bool:
        """Checks if the message should be ignored."""
        conditions = [
            (update.message is None,
             "Message is not text, skipping spam check"),
            (self.config.is_user_trusted(update.message.from_user.id), 
             f"User {update.message.from_user.id} is trusted, skipping spam check"),
            (not self.config.is_chat_moderated(update.message.chat_id), 
             f"Chat {update.message.chat_id} is not moderated, skipping spam check"),
            (self.config.is_admin(update.message.from_user.id), 
             f"User {update.message.from_user.id} is admin, skipping spam check"),
        ]

        for condition, message in conditions:
            if condition:
                self.logger.debug(f"[{self._name}] {message}")
                return True
        return False

    async def _on_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Adds the user to the trusted list if the message is not spam."""
        self.logger.info(f"[{self._name}] Message from user {update.message.from_user.id} is not spam")

    async def __on_filter_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Executed when the message passes all filters successfully."""
        self.logger.debug(f"[{self._name}] Message from user {update.message.from_user.id} passed all filters, trusting user..")
        self.config.trust(update.message.from_user.id)

    from typing import final

    @final
    async def apply(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Applies the spam filter to the incoming message."""
        if self._is_message_should_be_ignored(update):
            return
        if self._is_spam(update, context):
            await self._on_spam(update, context)
            return
        else:
            await self._on_pass(update, context)

        if self.next_filter:
            await self.next_filter.apply(update, context)
        else:
            await self.__on_filter_pass(update, context)
