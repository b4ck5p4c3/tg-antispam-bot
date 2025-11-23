from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler, admin_command, get_argument_value, get_int_argument_value
from src.handlers.spam_filters.ForwardSpamFilter.ForwardSpamFilter import get_forward_channel_id, get_channel_id
from src.telegram.EnrichedUpdate import EnrichedUpdate

BANNED_USER_MESSAGE_MAX_LEN_AUDIT = 200


def _extract_ban_user_id(update: EnrichedUpdate) -> int | None:
    if update.message.reply_to_message is not None:
        return update.message.reply_to_message.from_user.id
    user_id = get_int_argument_value(update, 1)
    return user_id

def _extract_community_id(update: EnrichedUpdate) -> int | None:
    reply = update.message.reply_to_message
    if reply is not None and reply.forward_origin is not None:
        return get_channel_id(reply.forward_origin)
    community_id = get_int_argument_value(update, 1)
    return community_id

class ManualModerationCommandsHandler(BaseHandler):

    @admin_command
    async def handle_ban_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /ban command."""
        ban_user_id = _extract_ban_user_id(update)
        await self.telegram_helper.delete_message_with_delay(context, update.message, 20)
        if await self.config.is_admin(ban_user_id, update.effective_chat.id):
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.durachok)
            return
        if ban_user_id is None:
            await self.telegram_helper.send_temporary_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.ban_user_not_found, remove_in_seconds=120)
            return
        chat_id = update.effective_chat.id
        try:
            await self.telegram_helper.ban_chat_member(context, chat_id=chat_id, user_id=ban_user_id)
        except TelegramError as e:
            self.logger.warning(f"Failed to ban user {ban_user_id}: {e}")
            await self.telegram_helper.send_temporary_message(context, chat_id=chat_id,
                                                    text=update.locale.ban_failed.format(
                                                        user_id=ban_user_id, error=e.message
                                                    ), remove_in_seconds=120)
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

    @admin_command
    async def handle_ban_community(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /banc command."""
        community_id = _extract_community_id(update)
        if community_id is None:
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.ban_community_not_found)
            await self.telegram_helper.audit_log(context, update.message, update.locale.audit_log_community_not_found)
            return
        if self.config.is_channel_banned(community_id):
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.community_already_banned.format(
                                                        community_id=community_id))
            return
        try:
            self.config.ban_channel(community_id)
            await self.telegram_helper.send_temporary_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.ban_community_success.format(
                                                        community_id=community_id))
            await self.telegram_helper.delete_message_with_delay(context, update.message)
            await self.telegram_helper.audit_log(context, update.message, update.locale.audit_log_community_banned_by_id
                                                 .format(community_id=community_id, banned_by=update.effective_user,
                                                         chat=update.effective_chat))
        except Exception as e:
            self.logger.error(f"Failed to ban community {community_id}: {e}")
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.ban_community_failed.format(
                                                        community_id=community_id, error=str(e)))