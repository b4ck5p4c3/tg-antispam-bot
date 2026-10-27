import re

from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler, admin_command
from src.handlers.CommandHelp import command_help
from src.telegram.EnrichedUpdate import EnrichedUpdate


class TrustCommandsHandler(BaseHandler):
    @admin_command
    @command_help(
        {"command": "trust <user_id|@username>", "locale_id": "help_trust_user"},
        module="help_module_moderation",
    )
    async def handle_trust_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        args = update.message.text.split()[1:]
        if len(args) != 1:
            await self._reply(update, context, update.locale.trust_usage)
            return

        target = args[0]
        if re.fullmatch(r"[1-9][0-9]*", target):
            try:
                user_id = int(target)
            except ValueError:
                await self._reply(update, context, update.locale.trust_usage)
                return
            if user_id > 2**63 - 1:
                await self._reply(update, context, update.locale.trust_usage)
                return
        elif re.fullmatch(r"@[A-Za-z0-9_]+", target):
            cached_user = self.state.get_cached_user_by_username(target)
            if cached_user is None:
                await self._reply(update, context, update.locale.trust_username_not_found)
                return
            user_id = cached_user.id
            try:
                member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
            except TelegramError as error:
                self.logger.warning("Failed to resolve trust target %s: %s", target, error)
                await self._reply(update, context, update.locale.trust_failed)
                return
            if (member.user.username or "").casefold() != target[1:].casefold():
                await self._reply(update, context, update.locale.trust_username_changed)
                return
        else:
            await self._reply(update, context, update.locale.trust_usage)
            return

        self.state.trust(user_id)
        self.logger.info(
            "User %s trusted by admin %s in chat %s",
            user_id, update.effective_user.id, update.effective_chat.id,
        )
        await self._reply(update, context, update.locale.trust_success.format(user_id=user_id))

    async def _reply(self, update: EnrichedUpdate, context: CallbackContext, text: str) -> None:
        await self.telegram_helper.send_message(
            context, update.effective_chat.id, text, parse_mode=None,
            reply_to_message_id=update.message.message_id,
        )
