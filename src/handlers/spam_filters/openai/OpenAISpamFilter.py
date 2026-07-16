import re

from telegram import ChatPermissions
from telegram.ext import CallbackContext

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.handlers.spam_filters.openai.OpenAIConfig import OpenAIFilterConfig
from src.handlers.spam_filters.openai.OpenAIWatchdog import OpenAIWatchdog
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.TelegramHelper import TelegramHelper
from src.util.data.BotState import BotState


def prepare_message_for_ai(update: EnrichedUpdate) -> str:
    if update.message is None:
        message_text = "<Message is not text>"
    else:
        message_text = TelegramHelper.extract_message_text(update.message) or "<Message is not text>"
    if len(update.recognized_photos) != 0:
        message_text += "\n\n###\n Recognized content:\n"
    for photo_recognition in update.recognized_photos:
        message_text += f"PHOTO CONTENT START\n{photo_recognition.ocr_text}\nPHOTO CONTENT END\n\n"
    return message_text


class OpenAISpamFilter(SpamFilter):
    _NOT_FOUND = -1
    __MESSAGE_SPAMNESS_MAP = {}
    _filter_name = "OpenAI"

    def __init__(
            self,
            state: BotState,
            openai_config: OpenAIFilterConfig,
            openai_watchdog: OpenAIWatchdog,
    ):
        super().__init__(state)
        self.openai_config = openai_config
        self.openai_watchdog = openai_watchdog

    def _find_spamness_percent(self, text: str) -> int:
        percent_search = list(re.finditer(r"(\d+)%", text))
        if percent_search:
            spamness_percent = percent_search[-1].group(1)
            try:
                spamness_percent = int(spamness_percent)
            except ValueError:
                self.logger.error(f"Failed to parse spamness percent from OpenAI response: {text}")
                return self._NOT_FOUND
            return spamness_percent
        else:
            self.logger.error(f"Failed to parse spamness percent from OpenAI response: {text}")
            return self._NOT_FOUND

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        answer_text = await self.openai_watchdog.analyze_message(context, prepare_message_for_ai(update))
        if answer_text is None:
            return False
        spamness_percent = self._find_spamness_percent(answer_text)
        if spamness_percent == self._NOT_FOUND:
            return False
        self.logger.info(f"Spamness of message {update.message.id}: {spamness_percent}%")
        self.__MESSAGE_SPAMNESS_MAP[update.message.id] = spamness_percent
        return spamness_percent >= self.openai_config.min_spamness_percent

    async def _on_spam(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the action to take when a message is identified as spam."""
        user = self.telegram_helper.extract_message_user(update.message)
        chat_id = update.message.chat_id
        await self.telegram_helper.try_remove_message(context, update.message)
        if user is None:
            await self.telegram_helper.ban_message_author(context, update.message)
            return
        await self.telegram_helper.restrict_chat_member(context, chat_id, user.id,
                                                        ChatPermissions(can_send_messages=False))
        ban_message = await self.telegram_helper.send_message(context, chat_id, self._get_restrict_message(update))

        await self.telegram_helper.delete_message_with_delay(context, ban_message,
                                                             self.openai_config.ban_notification_message_delete_delay_sec)
        context.job_queue.run_once(lambda ctx: self.telegram_helper.ban_message_author(context, update.message),
                                   self.openai_config.ban_delay_sec)

    async def _on_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        await super()._on_pass(update, context)
        if update.message.id in self.__MESSAGE_SPAMNESS_MAP:
            if self.__MESSAGE_SPAMNESS_MAP[update.message.id] >= self.openai_config.sussy_message_min_spamness:
                await self.telegram_helper.add_message_reaction(context, update.message,
                                                                self.openai_config.sussy_message_reaction)
            del self.__MESSAGE_SPAMNESS_MAP[update.message.id]

    def _get_restrict_message(self, update: EnrichedUpdate) -> str:
        user = self.telegram_helper.extract_message_user(update.message)
        return update.locale.openai_user_ban_notification.format(
            user=user,
            spamness=self.__MESSAGE_SPAMNESS_MAP[update.message.id],
            ban_delay_min=self.openai_config.ban_delay_sec // 60
        )
