from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler, admin_command
from src.telegram.EnrichedUpdate import EnrichedUpdate


class ConfigurationCommandsHandler(BaseHandler):

    @admin_command
    async def handle_add_moderable_chat(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /moderate command."""
        chat_id = update.message.chat_id
        if self.config.is_chat_moderated(chat_id):
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.chat_already_moderated.format(chat_id=chat_id))
            return
        self._add_chat_to_moderable(chat_id)
        await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                text=update.locale.chat_added_to_moderate.format(chat_id=chat_id))

    @admin_command
    async def handle_remove_moderable_chat(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /stop_moderate command."""
        chat_id = update.message.chat_id
        if not self.config.is_chat_moderated(chat_id):
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.chat_not_moderated.format(chat_id=chat_id))
            return
        self._remove_chat_from_moderable(chat_id)
        await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                text=update.locale.chat_removed_from_moderate.format(chat_id=chat_id))

    def _add_chat_to_moderable(self, chat_id: int) -> None:
        """Adds a chat to the moderable list."""
        self.config.moderate_chat(chat_id)
        self.logger.info(f"Chat {chat_id} added to the moderable list.")

    def _remove_chat_from_moderable(self, chat_id: int) -> None:
        """Removes a chat from the moderable list."""
        self.config.stop_chat_moderating(chat_id)
        self.logger.info(f"Chat {chat_id} removed from the moderable list.")
