from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler, admin_command
from src.telegram.EnrichedUpdate import EnrichedUpdate

BANNED_USER_MESSAGE_MAX_LEN_AUDIT = 100


class ManualModerationCommandsHandler(BaseHandler):

    @admin_command
    async def handle_ban_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /ban command."""
        ban_user_id = self.__extract_ban_user_id(update)
        if await self.config.is_admin(ban_user_id, update.effective_chat.id):
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.durachok)
            return
        if ban_user_id is None:
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.ban_user_not_found)
            return
        chat_id = update.effective_chat.id
        try:
            await self.telegram_helper.ban_chat_member(context, chat_id=chat_id, user_id=ban_user_id)
        except TelegramError as e:
            self.logger.warning(f"Failed to ban user {ban_user_id}: {e}")
            await self.telegram_helper.send_message(context, chat_id=chat_id,
                                                    text=update.locale.ban_failed.format(
                                                        user_id=ban_user_id, error=e.message
                                                    ))
            return
        if update.message.reply_to_message is not None:
            await self.telegram_helper.try_remove_message(context, update.message.reply_to_message)
        await self.telegram_helper.send_temporary_message(context, chat_id=chat_id,
                                                text=update.locale.ban_success.format(user_id=ban_user_id), remove_in_seconds=20)
        if update.message.reply_to_message is not None:
            truncated_message = update.message.reply_to_message.text[:BANNED_USER_MESSAGE_MAX_LEN_AUDIT]

            await self.telegram_helper.audit_log(context, update.message, update.locale.audit_log_user_banned_by_reply
                                                 .format(banned_user=update.message.reply_to_message.from_user, banned_by=update.effective_user,
                                                         message=truncated_message, chat=update.effective_chat))
        else:
            await self.telegram_helper.audit_log(context, update.message, update.locale.audit_log_user_banned_by_id
                                                 .format(banned_id=ban_user_id, banned_by=update.effective_user, chat=update.effective_chat))



    def __extract_ban_user_id(self, update: EnrichedUpdate) -> int:
        if update.message.reply_to_message is not None:
            return update.message.reply_to_message.from_user.id
        elif update.message.text is not None:
            splitted = update.message.text.split(" ")
            if len(splitted) > 1 and splitted[1].isdigit():
                return int(splitted[1])