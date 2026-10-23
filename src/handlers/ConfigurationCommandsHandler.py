from typing import Optional

from telegram import Chat
from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.CommandHelp import command_help
from src.handlers.BaseHandler import BaseHandler, admin_command
from src.telegram.EnrichedUpdate import EnrichedUpdate


class ConfigurationCommandsHandler(BaseHandler):

    @admin_command
    @command_help(
        {
            "command": "moderate", "locale_id": "help_moderate",
            "menu_locale_id": "help_menu_moderate",
        },
        {'command': 'moderate ls', 'locale_id': 'help_moderate_ls'},
        module="help_module_configuration",
    )
    async def handle_add_moderable_chat(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /moderate command."""
        args = context.args or []
        if args == ["ls"]:
            await self._list_moderated_chats(update, context)
            return
        if args:
            await self.telegram_helper.send_message(
                context, update.effective_chat.id, update.locale.moderate_usage,
                parse_mode=None,
            )
            return
        chat_id = update.message.chat_id
        if self.state.is_chat_moderated(chat_id):
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.chat_already_moderated.format(chat_id=chat_id))
            return
        self._add_chat_to_moderable(chat_id)
        await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                text=update.locale.chat_added_to_moderate.format(chat_id=chat_id))

    async def _list_moderated_chats(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        locale = update.locale
        chat_ids = list(dict.fromkeys(self.state.moderated_chat_ids))
        text = locale.moderated_chats_header if chat_ids else locale.moderated_chats_empty
        for index, chat_id in enumerate(chat_ids, start=1):
            try:
                chat = await self.telegram_helper.get_chat(context, chat_id)
                name = self.telegram_helper.get_chat_display_name(chat)
            except TelegramError as error:
                self.logger.warning("Could not get moderated chat %s: %s", chat_id, error)
                name = locale.moderated_chat_unavailable
            line = locale.moderated_chat_entry.format(index=index, chat=name, chat_id=chat_id)
            if len(text) + len(line) + 1 > 3800:
                await self.telegram_helper.send_message(
                    context, update.effective_chat.id, text, parse_mode=None,
                )
                text = locale.moderated_chats_header
            text += "\n" + line
        await self.telegram_helper.send_message(
            context, update.effective_chat.id, text, parse_mode=None,
        )

    @admin_command
    @command_help(
        {'command': 'abandon', 'locale_id': 'help_abandon'},
        module="help_module_configuration",
    )
    async def handle_remove_moderable_chat(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /stop_moderate command."""
        chat_id = update.message.chat_id
        if not self.state.is_chat_moderated(chat_id):
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.chat_not_moderated.format(chat_id=chat_id))
            return
        self._remove_chat_from_moderable(chat_id)
        await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                text=update.locale.chat_removed_from_moderate.format(chat_id=chat_id))

    def _add_chat_to_moderable(self, chat_id: int) -> None:
        """Adds a chat to the moderable list."""
        self.state.moderate_chat(chat_id)
        self.logger.info(f"Chat {chat_id} added to the moderable list.")

    def _remove_chat_from_moderable(self, chat_id: int) -> None:
        """Removes a chat from the moderable list."""
        self.state.stop_chat_moderating(chat_id)
        self.logger.info(f"Chat {chat_id} removed from the moderable list.")

    @admin_command
    @command_help(
        {'command': 'set_audit_log', 'locale_id': 'help_set_audit_log'},
        module="help_module_configuration",
    )
    async def set_channel_as_audit_log(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /set_audit_log command."""
        new_chat = update.effective_chat
        previous_chat_id: Optional[int] = self.state.get_audit_log_chat_id()
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
                                                    text=update.locale.audit_log_chat_set.format(chat_id=new_chat.id,
                                                                                                 chat_name=new_chat.title,
                                                                                                 user=update.effective_user))
        self.state.set_audit_log_chat(new_chat.id)
        self.logger.info(f"Chat {new_chat.id} set as audit log chat by user {update.effective_user.id}")

    @admin_command
    @command_help(
        {'command': 'unset_audit_log', 'locale_id': 'help_unset_audit_log'},
        module="help_module_configuration",
    )
    async def unset_channel_as_audit_log(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /unset_audit_log command."""
        current_audit_log_chat_id = self.state.get_audit_log_chat_id()
        if current_audit_log_chat_id is None:
            await self.telegram_helper.send_temporary_message(context, chat_id=update.effective_chat.id,
                                                              text=update.locale.audit_log_chat_not_found)
            return
        self.state.remove_audit_log_chat()
        for chat_id in {current_audit_log_chat_id, update.effective_chat.id}:
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.audit_log_chat_removed.format(
                                                        user=update.effective_user))
        self.logger.info(f"Chat {current_audit_log_chat_id} unset as audit log chat by user {update.effective_user.id}")
