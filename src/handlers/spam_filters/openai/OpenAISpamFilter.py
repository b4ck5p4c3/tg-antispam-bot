from telegram import ChatPermissions
from telegram.ext import CallbackContext
from telegram.helpers import escape_markdown

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.handlers.spam_filters.openai.OpenAIConfig import OpenAIFilterConfig
from src.handlers.spam_filters.openai.OpenAIModels import OpenAIMessageInput
from src.handlers.spam_filters.openai.OpenAIWatchdog import OpenAIWatchdog
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.TelegramHelper import TelegramHelper
from src.util.DevelopmentMode import get_development_delay_seconds, is_development_mode
from src.util.data.BotState import BotState


class OpenAISpamFilter(SpamFilter):
    _filter_name = "OpenAI"
    _DEVELOPMENT_BAN_DELAY_SECONDS = 5

    def __init__(
            self,
            state: BotState,
            openai_config: OpenAIFilterConfig,
            openai_watchdog: OpenAIWatchdog,
    ):
        super().__init__(state)
        self.openai_config = openai_config
        self.openai_watchdog = openai_watchdog
        self._spam_reasons: dict[tuple[int, int], str] = {}
        self._ban_delay_seconds = self._get_ban_delay_seconds()

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns true if message is spam."""
        classification = await self.openai_watchdog.classify_message(
            context,
            self._prepare_message_input(update),
        )
        if classification is None:
            return False

        message = update.message
        self.logger.info(
            "OpenAI verdict for message %s: %s (%s)",
            message.id,
            classification.verdict,
            classification.reason,
        )
        if classification.verdict != "spam":
            return False

        self._spam_reasons[(message.chat_id, message.id)] = classification.reason
        return True

    async def _on_spam(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the action to take when a message is identified as spam."""
        user = self.telegram_helper.extract_message_user(update.message)
        chat_id = update.message.chat_id
        await self.telegram_helper.try_remove_message(context, update.message)
        if user is None:
            self._remove_spam_reason(update)
            await self.telegram_helper.ban_message_author(context, update.message)
            return
        await self.telegram_helper.restrict_chat_member(
            context,
            chat_id,
            user.id,
            ChatPermissions(can_send_messages=False),
        )
        ban_message = await self.telegram_helper.send_message(
            context,
            chat_id,
            self._get_restrict_message(update),
        )
        self._remove_spam_reason(update)

        await self.telegram_helper.delete_message_with_delay(
            context,
            ban_message,
            self.openai_config.ban_notification_message_delete_delay_sec,
        )
        context.job_queue.run_once(
            lambda job_context: self.telegram_helper.ban_message_author(job_context, update.message),
            self._ban_delay_seconds,
        )

    def _prepare_message_input(self, update: EnrichedUpdate) -> OpenAIMessageInput:
        message = update.message
        replied_to_message = ""
        if message.reply_to_message is not None:
            replied_to_message = TelegramHelper.extract_message_text(message.reply_to_message) or ""

        attachment_transcripts = [
            recognized_photo.ocr_text
            for recognized_photo in (update.recognized_photos or ())
            if recognized_photo.ocr_text.strip() != ""
        ]
        return OpenAIMessageInput(
            target_message=TelegramHelper.extract_message_text(message) or "",
            attachment_transcript="\n\n".join(attachment_transcripts),
            replied_to_message=replied_to_message,
        )

    def _get_restrict_message(self, update: EnrichedUpdate) -> str:
        user = self.telegram_helper.extract_message_user(update.message)
        reason = self._spam_reasons[(update.message.chat_id, update.message.id)]
        return update.locale.openai_user_ban_notification.format(
            user=user,
            reason=escape_markdown(reason),
            ban_delay_min=max(1, self._ban_delay_seconds // 60),
        )

    def _remove_spam_reason(self, update: EnrichedUpdate) -> None:
        self._spam_reasons.pop((update.message.chat_id, update.message.id), None)

    def _get_ban_delay_seconds(self) -> int:
        if not is_development_mode():
            return self.openai_config.ban_delay_sec
        return get_development_delay_seconds(
            "DEVELOPMENT_SPAM_BAN_DELAY_SECONDS",
            self._DEVELOPMENT_BAN_DELAY_SECONDS,
        )
