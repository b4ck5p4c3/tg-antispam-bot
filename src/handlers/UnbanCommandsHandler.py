import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.constants import ChatMemberStatus
from telegram.error import BadRequest, TelegramError
from telegram.ext import CallbackContext

from src.handlers.CommandHelp import command_help
from src.handlers.BaseHandler import BaseHandler
from src.handlers.ButtonClickHandler import button_click
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.telegram.KeyboardData import KeyboardData
from src.util.data.BotState import UnbanChat, UnbanRequest


class UnbanKeyboardData(KeyboardData):
    key_id: str = "UNBAN"
    target_chat_id: int


class UnbanCommandsHandler(BaseHandler):
    @command_help(
        {'command': 'unban', 'locale_id': 'help_unban_reply', 'admin': True},
        {'command': 'unban <user_id>', 'locale_id': 'help_unban_id', 'admin': True},
        {'command': 'unban <@username>', 'locale_id': 'help_unban_username', 'admin': True},
        module="help_module_moderation",
    )
    async def handle_unban_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        message = update.message
        args = message.text.split()[1:]
        source_chat_id = None
        expected_username = None
        ban = None
        if not args and message.reply_to_message is not None:
            reply = message.reply_to_message
            ban = self.state.get_audit_log_ban(reply.chat_id, reply.message_id)
        access_chats = set(self.state.moderated_chat_ids)
        if ban is not None:
            access_chats.add(ban.banned_chat_id)
        authorized_chats = {
            chat_id for chat_id in access_chats
            if await self._is_admin(update.effective_user.id, chat_id)
        }
        if not authorized_chats or (ban is not None and ban.banned_chat_id not in authorized_chats):
            return

        if not args and message.reply_to_message is not None:
            if ban is None:
                await self._reply(update, context, update.locale.unban_audit_log_not_found)
                return
            user_id = ban.user_id
            source_chat_id = ban.banned_chat_id
        elif len(args) == 1 and re.fullmatch(r"[1-9][0-9]*", args[0]):
            user_id = int(args[0])
        elif len(args) == 1 and re.fullmatch(r"@[A-Za-z0-9_]+", args[0]):
            cached_user = self.state.get_cached_user_by_username(args[0])
            if cached_user is None:
                await self._reply(update, context, update.locale.unban_username_not_found)
                return
            user_id = cached_user.id
            expected_username = args[0][1:].casefold()
        else:
            await self._reply(update, context, update.locale.unban_usage)
            return

        request = UnbanRequest(user_id=user_id, expected_username=expected_username)
        if source_chat_id is not None:
            request.chats[source_chat_id] = UnbanChat(title=await self._chat_title(context, source_chat_id))
            if not await self._unban_if_authorized(request, source_chat_id, update, context):
                return

        for chat_id in dict.fromkeys(self.state.moderated_chat_ids):
            if chat_id == source_chat_id:
                continue
            try:
                member = await context.bot.get_chat_member(chat_id, user_id)
            except TelegramError as error:
                self.logger.warning("Failed to check ban for user %s in chat %s: %s", user_id, chat_id, error)
                request.scan_errors[chat_id] = str(error)
                continue
            if member.status == ChatMemberStatus.BANNED:
                request.chats[chat_id] = UnbanChat(title=await self._chat_title(context, chat_id))

        if request.chats and not authorized_chats.intersection(request.chats):
            return
        if source_chat_id is None and len(request.chats) == 1 and not request.scan_errors:
            chat_id = next(iter(request.chats))
            if not await self._unban_if_authorized(request, chat_id, update, context):
                return

        response = await self._reply(
            update, context, self._response_text(request, update),
            reply_markup=self._keyboard(request, update),
        )
        self.state.save_unban_request(response.chat_id, response.message_id, request)

    @button_click
    async def on_unban_button_click(
            self, button_data: UnbanKeyboardData, update: EnrichedUpdate, context: CallbackContext,
    ) -> None:
        query = update.callback_query
        chat_id = button_data.target_chat_id
        if not await self._is_admin(update.effective_user.id, chat_id):
            await query.answer()
            return
        message = query.message
        if message is None:
            await query.answer(update.locale.unban_request_not_found, show_alert=True)
            return
        request = self.state.get_unban_request(message.chat_id, message.message_id)
        if request is None or chat_id not in request.chats:
            await query.answer(update.locale.unban_request_not_found, show_alert=True)
            return
        if request.chats[chat_id].status != "pending":
            await query.answer(update.locale.unban_already_processed)
            await self._edit_response(request, update, context)
            return
        if not self.state.is_chat_moderated(chat_id):
            await query.answer(update.locale.chat_not_moderated.format(chat_id=chat_id), show_alert=True)
            return

        await query.answer()
        await self._unban(request, chat_id, update, context)
        self.state.save_unban_request(message.chat_id, message.message_id, request)
        await self._edit_response(request, update, context)

    async def _unban_if_authorized(
            self, request: UnbanRequest, chat_id: int, update: EnrichedUpdate, context: CallbackContext,
    ) -> bool:
        if not await self._is_admin(update.effective_user.id, chat_id):
            return False
        await self._unban(request, chat_id, update, context)
        return True

    async def _unban(
            self, request: UnbanRequest, chat_id: int, update: EnrichedUpdate, context: CallbackContext,
    ) -> None:
        result = request.chats[chat_id]
        result.error = None
        try:
            member = await context.bot.get_chat_member(chat_id, request.user_id)
            if request.expected_username is not None:
                actual_username = (member.user.username or "").casefold()
                if actual_username != request.expected_username:
                    result.error = update.locale.unban_username_changed
                    return
            if member.status != ChatMemberStatus.BANNED:
                result.status = "not_banned"
                return
            await self.telegram_helper.unban_chat_member(context, chat_id, request.user_id)
        except TelegramError as error:
            self.logger.warning("Failed to unban user %s in chat %s: %s", request.user_id, chat_id, error)
            result.error = str(error)
            return
        result.status = "unbanned"

    async def _is_admin(self, user_id: int, chat_id: int) -> bool:
        try:
            return await self.state.is_admin(user_id, chat_id)
        except TelegramError as error:
            self.logger.warning("Failed to check admin %s in chat %s: %s", user_id, chat_id, error)
            return False

    async def _chat_title(self, context: CallbackContext, chat_id: int) -> str:
        try:
            chat = await self.telegram_helper.get_chat(context, chat_id)
            return self.telegram_helper.get_chat_display_name(chat)
        except TelegramError:
            return str(chat_id)

    def _response_text(self, request: UnbanRequest, update: EnrichedUpdate) -> str:
        locale = update.locale
        lines = [locale.unban_result_header.format(user_id=request.user_id)]
        if not request.chats and not request.scan_errors:
            lines.append(locale.unban_not_banned)
        if any(chat.status == "pending" for chat in request.chats.values()):
            lines.append(locale.unban_choose_chats)
        for chat_id, chat in request.chats.items():
            label = f"{chat.title} ({chat_id})"
            if chat.status == "unbanned":
                lines.append(locale.unban_success.format(chat=label))
            elif chat.status == "not_banned":
                lines.append(locale.unban_chat_not_banned.format(chat=label))
            else:
                lines.append(locale.unban_pending.format(chat=label))
            if chat.error is not None:
                lines.append(locale.unban_failed.format(chat=label, error=chat.error))
        for chat_id, error in request.scan_errors.items():
            lines.append(locale.unban_scan_failed.format(chat_id=chat_id, error=error))
        return "\n\n".join(lines)

    @staticmethod
    def _keyboard(request: UnbanRequest, update: EnrichedUpdate) -> InlineKeyboardMarkup | None:
        buttons = [
            [InlineKeyboardButton(
                text=update.locale.unban_button.format(chat=f"{chat.title} ({chat_id})"),
                callback_data=UnbanKeyboardData(target_chat_id=chat_id).model_dump(),
            )]
            for chat_id, chat in request.chats.items() if chat.status == "pending"
        ]
        return InlineKeyboardMarkup(buttons) if buttons else None

    async def _reply(self, update: EnrichedUpdate, context: CallbackContext, text: str, **kwargs) -> Message:
        return await self.telegram_helper.send_message(
            context, update.effective_chat.id, text, parse_mode=None,
            reply_to_message_id=update.message.message_id, **kwargs,
        )

    async def _edit_response(self, request: UnbanRequest, update: EnrichedUpdate, context: CallbackContext) -> None:
        message = update.callback_query.message
        try:
            await context.bot.edit_message_text(
                chat_id=message.chat_id, message_id=message.message_id,
                text=self._response_text(request, update), parse_mode=None,
                reply_markup=self._keyboard(request, update),
            )
        except BadRequest as error:
            if "message is not modified" not in str(error).lower():
                raise
