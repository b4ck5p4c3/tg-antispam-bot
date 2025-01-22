from Tools.scripts.pindent import usage
from typing import Optional

from telegram import Chat
from telegram.error import TelegramError
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


    @admin_command
    async def set_channel_as_audit_log(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /set_audit_log command."""
        new_chat = update.effective_chat
        previous_chat_id: Optional[int] = self.config.get_audit_log_chat_id()
        if previous_chat_id is not None:
            chat_name = "Unknown"
            try:
                chat: Chat = await self.telegram_helper.get_chat(context, previous_chat_id)
                chat_name = chat.title
            except TelegramError as e:
                self.logger.warning(f"Failed to get chat {previous_chat_id}: {e}")
            for chat_id in {new_chat.id, previous_chat_id}:
                await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                        text=update.locale.audit_log_chat_updated.format(
                                                            old_chat_name=chat_name, old_chat_id=previous_chat_id,
                                                            new_chat_name=new_chat.title, new_chat_id=new_chat.id,
                                                            user=update.effective_user))
        else:
            await self.telegram_helper.send_message(context, chat_id=new_chat.id,
                                                    text=update.locale.audit_log_chat_set.format(chat_id=new_chat.id, chat_name=new_chat.title, user=update.effective_user))
        self.config.set_audit_log_chat(new_chat.id)
        self.logger.info(f"Chat {new_chat.id} set as audit log chat by user {update.effective_user.id}")

    @admin_command
    async def unset_channel_as_audit_log(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /unset_audit_log command."""
        current_audit_log_chat_id = self.config.get_audit_log_chat_id()
        if current_audit_log_chat_id is None:
            await self.telegram_helper.send_temporary_message(context, chat_id=update.effective_chat.id,
                                                    text=update.locale.audit_log_chat_not_found)
            return
        self.config.remove_audit_log_chat()
        for chat_id in {current_audit_log_chat_id, update.effective_chat.id}:
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.audit_log_chat_removed.format(user=update.effective_user))
        self.logger.info(f"Chat {current_audit_log_chat_id} unset as audit log chat by user {update.effective_user.id}")
