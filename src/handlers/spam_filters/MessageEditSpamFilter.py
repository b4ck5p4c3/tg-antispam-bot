from telegram.ext import CallbackContext

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.handlers.spam_filters.openai.OpenAIConfig import OpenAIFilterConfig
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.data.BotState import BotState, MessageEditHistory, MessageRevision


class MessageEditSpamFilter(SpamFilter):
    _filter_name = "MessageEditSpamFilter"

    def __init__(self, state: BotState, config: OpenAIFilterConfig):
        super().__init__(state)
        self.config = config

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        message = update.effective_message
        user = self.telegram_helper.extract_message_user(message)
        if user is None:
            return False

        history = self.state.get_message_edit_history(message.chat_id, user.id)
        if history is None:
            history = MessageEditHistory(message_id=message.id)
        if history.message_id != message.id:
            return False

        if update.edited_message is not None:
            history.edit_count += 1
        history.last_update_id = update.update_id
        exceeded_limit = history.edit_count > self.config.max_message_edits
        if not exceeded_limit:
            replied_to_message = ""
            if message.reply_to_message is not None:
                replied_to_message = self.telegram_helper.extract_message_text(message.reply_to_message) or ""
            history.revisions.append(MessageRevision(
                target_message=self.telegram_helper.extract_message_text(message) or "",
                replied_to_message=replied_to_message,
            ))
        self.state.save_message_edit_history(message.chat_id, user.id, history)
        update.set_message_history(history)

        if exceeded_limit:
            self.logger.info(
                "[chat_id=%s message_id=%s] Message edit spam limit exceeded: %s > %s",
                message.chat_id, message.id, history.edit_count, self.config.max_message_edits,
            )
        return exceeded_limit
