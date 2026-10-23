from telegram.error import TelegramError
from telegram.ext import CallbackContext
from telegram.helpers import escape_markdown

from src.handlers.CommandHelp import command_help
from src.handlers.BaseHandler import BaseHandler, admin_command, get_argument_value, get_int_argument_value
from src.handlers.spam_filters.ForwardSpamFilter.ForwardSpamFilter import get_forward_channel_id, get_channel_id
from src.telegram.EnrichedUpdate import EnrichedUpdate




def _extract_ban_user_id(update: EnrichedUpdate) -> int | None:
    if update.message.reply_to_message is not None:
        reply = update.message.reply_to_message
        if reply.sender_chat is None and reply.from_user is not None:
            return reply.from_user.id
        return None
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
    @command_help(
        {'command': 'ban', 'locale_id': 'help_ban_reply'},
        {'command': 'ban <user_id>', 'locale_id': 'help_ban_id'},
        {'command': 'ban <@username>', 'locale_id': 'help_ban_username'},
        module="help_module_moderation",
    )
    async def handle_ban_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /ban command."""
        reply_message = update.message.reply_to_message
        ban_user_id = _extract_ban_user_id(update)
        ban_sender_chat = None if reply_message is None else self.telegram_helper.extract_message_sender_chat(reply_message)
        await self.telegram_helper.delete_message_with_delay(context, update.message, 20)
        ban_username = None
        args = update.message.text.split()[1:]
        if reply_message is None and args and args[0].startswith("@"):
            cached_user = self.state.get_cached_user_by_username(args[0])
            if cached_user is None:
                await self.telegram_helper.send_temporary_message(
                    context, update.message.chat_id, update.locale.ban_username_not_found,
                    remove_in_seconds=120,
                )
                return
            ban_user_id = cached_user.id
            ban_username = args[0][1:].casefold()
        if reply_message is not None and self.telegram_helper.is_message_from_anonymous_admin(reply_message):
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.durachok)
            return
        if ban_user_id is not None and await self.state.is_admin(ban_user_id, update.effective_chat.id):
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.durachok)
            return
        if ban_user_id is None and ban_sender_chat is None:
            await self.telegram_helper.send_temporary_message(context, chat_id=update.message.chat_id,
                                                              text=update.locale.ban_user_not_found,
                                                              remove_in_seconds=120)
            return
        chat_id = update.effective_chat.id
        try:
            if ban_sender_chat is not None:
                await self.telegram_helper.ban_message_author(context, reply_message)
            else:
                if ban_username is not None:
                    member = await context.bot.get_chat_member(chat_id, ban_user_id)
                    if (member.user.username or "").casefold() != ban_username:
                        await self.telegram_helper.send_temporary_message(
                            context, chat_id, update.locale.ban_username_changed,
                            remove_in_seconds=120,
                        )
                        return
                await self.telegram_helper.ban_chat_member(context, chat_id=chat_id, user_id=ban_user_id)
        except TelegramError as e:
            if ban_sender_chat is not None:
                self.logger.warning(f"Failed to ban sender chat {ban_sender_chat.id}: {e}")
                error_text = update.locale.ban_channel_failed.format(
                    channel_id=ban_sender_chat.id, error=e.message
                )
            else:
                self.logger.warning(f"Failed to ban user {ban_user_id}: {e}")
                error_text = update.locale.ban_failed.format(
                    user_id=ban_user_id, error=e.message
                )
            await self.telegram_helper.send_temporary_message(context, chat_id=chat_id,
                                                              text=error_text, remove_in_seconds=120)
            return
        if reply_message is not None:
            await self.telegram_helper.try_remove_message(context, reply_message)
        if ban_sender_chat is not None:
            success_text = update.locale.ban_channel_success.format(channel_id=ban_sender_chat.id)
        else:
            success_text = update.locale.ban_success.format(user_id=ban_user_id)
        await self.telegram_helper.send_temporary_message(context, chat_id=chat_id,
                                                          text=success_text,
                                                          remove_in_seconds=20)
        if reply_message is not None:
            await self.telegram_helper.audit_log_ban_for_message(reply_message, update, context)
        else:
            audit_template = (
                update.locale.audit_log_user_banned_by_username if ban_username is not None
                else update.locale.audit_log_user_banned_by_id
            )
            await self.telegram_helper.audit_log(
                context, update.message,
                audit_template.format(
                    banned_id=ban_user_id, banned_by=update.effective_user,
                    chat=update.effective_chat, username=escape_markdown(ban_username or ""),
                ),
                banned_user_id=ban_user_id,
            )

    @admin_command
    @command_help(
        {'command': 'banc', 'locale_id': 'help_banc_reply'},
        {'command': 'banc <channel_id>', 'locale_id': 'help_banc_id'},
        module="help_module_moderation",
    )
    async def handle_ban_community(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the /banc command."""
        community_id = _extract_community_id(update)
        if community_id is None:
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.ban_community_not_found)
            await self.telegram_helper.audit_log(context, update.message, update.locale.audit_log_community_not_found)
            return
        if self.state.is_channel_banned(community_id):
            await self.telegram_helper.send_message(context, chat_id=update.message.chat_id,
                                                    text=update.locale.community_already_banned.format(
                                                        community_id=community_id))
            return
        try:
            self.state.ban_channel(community_id)
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
