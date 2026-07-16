from typing import Optional

from telegram import Message
from telegram.ext import CallbackContext

from src.TelegramHelper import TelegramHelper
from src.util.LoggerUtil import LoggerUtil
from src.util.data.BotState import BotState
from src.telegram.EnrichedUpdate import EnrichedUpdate


class SpamFilter:
    _filter_name = "Generic Filter"
    __ignored_message_types = [
        Message.left_chat_member, Message.new_chat_members
    ]

    def __init__(self, state: BotState, next_filter: Optional['SpamFilter'] = None):
        self.state = state
        self.logger = LoggerUtil.get_logger(type(self).__name__, self._filter_name)
        self.next_filter = next_filter
        self.telegram_helper = TelegramHelper(self.logger, state)

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns True if message is spam, otherwise False."""
        # Implement the spam checking logic here
        raise NotImplementedError("Subclasses should implement this method.")

    async def _on_spam(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Bans the user if the message is identified as spam."""
        sender_chat = self.telegram_helper.extract_message_sender_chat(update.message)
        sender_user = self.telegram_helper.extract_message_user(update.message)
        if sender_chat is not None:
            self.logger.info(
                "%s Moderation action: banning sender chat %s",
                self.__get_trace_id(update),
                sender_chat.id,
            )
        elif sender_user is not None:
            self.logger.info(
                "%s Moderation action: banning user %s",
                self.__get_trace_id(update),
                sender_user.id,
            )
        await self.telegram_helper.try_remove_message(context, update.message)
        await self.telegram_helper.ban_message_author(context, update.message)

    async def __get_ignore_reason(self, update: EnrichedUpdate) -> str | None:
        if update.message is None:
            return "update is not a message"
        sender_user = self.telegram_helper.extract_message_user(update.message)
        sender_user_id = None if sender_user is None else sender_user.id

        if self.__is_message_type_not_supported(update.message):
            return "message type is not supported"
        if self.telegram_helper.is_message_from_anonymous_admin(update.message):
            return "message was sent by an anonymous admin"
        if sender_user_id is not None and self.state.is_user_trusted(sender_user_id):
            return f"user {sender_user_id} is trusted"
        if not self.state.is_chat_moderated(update.message.chat_id):
            return f"chat {update.message.chat_id} is not moderated"
        if sender_user_id is not None and await self.state.is_admin(sender_user_id, update.effective_chat.id):
            return f"user {sender_user_id} is an admin"
        return None

    @staticmethod
    def __is_message_type_not_supported(message: Message) -> bool:
        return message.left_chat_member is not None or len(message.new_chat_members) != 0

    async def _on_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Hook executed when the message passes this filter."""

    async def __on_filter_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Executed when the message passes all filters successfully."""
        sender_user = self.telegram_helper.extract_message_user(update.message)
        if sender_user is None:
            self.logger.debug(
                "%s Message has no user author, skipping trust update",
                self.__get_trace_id(update),
            )
            return
        self.logger.debug(
            "%s Message passed all filters, trusting user %s",
            self.__get_trace_id(update),
            sender_user.id,
        )
        self.state.trust(sender_user.id)

    @staticmethod
    def __get_trace_id(update: EnrichedUpdate) -> str:
        if update.message is None:
            return f"[update_id={update.update_id}]"
        return f"[chat_id={update.message.chat_id} message_id={update.message.id}]"

    def __get_message_metadata(self, update: EnrichedUpdate) -> str:
        message = update.message
        if message is None:
            return "message=no"
        sender_user = self.telegram_helper.extract_message_user(message)
        sender_chat = self.telegram_helper.extract_message_sender_chat(message)
        return (
            f"sender_user_id={sender_user.id if sender_user is not None else 'none'} "
            f"sender_chat_id={sender_chat.id if sender_chat is not None else 'none'} "
            f"text={'yes' if self.telegram_helper.extract_message_text(message) else 'no'} "
            f"photo={'yes' if message.photo else 'no'} "
            f"forward={'yes' if message.forward_origin is not None else 'no'} "
            f"reply={'yes' if message.reply_to_message is not None else 'no'}"
        )

    async def __apply_filter(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        trace_id = self.__get_trace_id(update)
        filter_name = type(self).__name__
        self.logger.info("%s Filter check started", trace_id)

        try:
            is_spam = await self._is_spam(update, context)
        except Exception as error:
            self.logger.error(
                "%s Filter check failed: %s: %s",
                trace_id,
                type(error).__name__,
                error,
            )
            raise
        self.logger.info(
            "%s Filter check completed: result=%s",
            trace_id,
            "spam" if is_spam else "passed",
        )
        if is_spam:
            self.logger.info("%s Moderation action started", trace_id)
            try:
                await self._on_spam(update, context)
            except Exception as error:
                self.logger.error(
                    "%s Moderation action failed: %s: %s",
                    trace_id,
                    type(error).__name__,
                    error,
                )
                raise
            self.logger.info(
                "%s Spam check completed: result=spam detector=%s",
                trace_id,
                filter_name,
            )
            return

        await self._on_pass(update, context)
        if self.next_filter:
            await self.next_filter.__apply_filter(update, context)
            return

        await self.__on_filter_pass(update, context)
        self.logger.info("%s Spam check completed: result=not_spam", trace_id)

    from typing import final

    @final
    async def apply(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Applies the spam filter to the incoming message."""
        trace_id = self.__get_trace_id(update)
        self.logger.info(
            "%s Spam check started: %s",
            trace_id,
            self.__get_message_metadata(update),
        )
        ignore_reason = await self.__get_ignore_reason(update)
        if ignore_reason is not None:
            self.logger.info(
                "%s Spam check completed: result=skipped reason=%s",
                trace_id,
                ignore_reason,
            )
            return
        await self.__apply_filter(update, context)
