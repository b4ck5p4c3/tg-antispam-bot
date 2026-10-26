import re
import time
from math import ceil

from telegram import ChatPermissions, User
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError
from telegram.ext import CallbackContext
from telegram.helpers import escape_markdown

from src.handlers.BaseHandler import BaseHandler, admin_command
from src.handlers.CommandHelp import command_help
from src.telegram.EnrichedUpdate import EnrichedUpdate


DURATION_UNITS = {
    "s": 1, "S": 1,
    "m": 60,
    "h": 3600, "H": 3600,
    "d": 86400, "D": 86400,
    "w": 604800, "W": 604800,
    "M": 30 * 86400,
    "y": 365 * 86400, "Y": 365 * 86400,
    "c": 100 * 365 * 86400, "C": 100 * 365 * 86400,
}
DEFAULT_MUTE_DURATION = "1d"


def parse_mute_duration(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([sSmhHdDwWMyYcC])", value)
    if match is None:
        raise ValueError("Invalid mute duration")
    seconds = int(match[1]) * DURATION_UNITS[match[2]]
    if not 0 < seconds <= 2**63 - 1:
        raise ValueError("Mute duration is out of range")
    return seconds


def mute_permissions(allowed: bool) -> ChatPermissions:
    permissions = (
        ChatPermissions.all_permissions() if allowed else ChatPermissions.no_permissions()
    ).to_dict()
    # Forward Bot API fields that are missing from the pinned PTB version.
    permissions.update(can_react_to_messages=allowed, can_edit_tag=allowed)
    return ChatPermissions.de_json(permissions, bot=None)


class MuteCommandsHandler(BaseHandler):
    @admin_command
    @command_help(
        {"command": "mute [duration]", "locale_id": "help_mute_reply"},
        {"command": "mute <user_id|@username> [duration]", "locale_id": "help_mute_user"},
        module="help_module_moderation",
    )
    async def handle_mute_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        args = update.message.text.split()[1:]
        if len(args) > 2:
            await self._reply(update, context, update.locale.mute_usage)
            return
        target = None
        duration_arg = DEFAULT_MUTE_DURATION
        if len(args) == 2:
            target, duration_arg = args
        elif args:
            if args[0].startswith("@") or re.fullmatch(r"[0-9]+", args[0]):
                target = args[0]
            else:
                duration_arg = args[0]
        try:
            duration = parse_mute_duration(duration_arg)
        except ValueError:
            await self._reply(update, context, update.locale.mute_invalid_duration)
            return
        if duration < 30:
            duration_text = update.locale.mute_duration_minimum
            duration = 30
        else:
            quantity = int(duration_arg[:-1])
            unit = duration_arg[-1]
            unit = unit if unit == "M" else unit.lower()
            names = update.locale.mute_duration_units[unit]
            duration_text = f"{quantity} {names[0] if quantity == 1 else names[1]}"
        await self._apply(update, context, target, duration, duration_text)

    @admin_command
    @command_help(
        {"command": "unmute", "locale_id": "help_unmute_reply"},
        {"command": "unmute <user_id|@username>", "locale_id": "help_unmute_user"},
        module="help_module_moderation",
    )
    async def handle_unmute_user(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        args = update.message.text.split()[1:]
        if len(args) > 1:
            await self._reply(update, context, update.locale.unmute_usage)
            return
        await self._apply(update, context, args[0] if args else None)

    async def _resolve_target(
            self, update: EnrichedUpdate, context: CallbackContext, target: str | None,
    ) -> User | None:
        expected_username = None
        if target is not None:
            if re.fullmatch(r"[1-9][0-9]*", target):
                try:
                    user_id = int(target)
                except ValueError:
                    await self._reply(update, context, update.locale.mute_user_not_found)
                    return None
                if user_id > 2**63 - 1:
                    await self._reply(update, context, update.locale.mute_user_not_found)
                    return None
            elif re.fullmatch(r"@[A-Za-z0-9_]+", target):
                cached_user = self.state.get_cached_user_by_username(target)
                if cached_user is None:
                    await self._reply(update, context, update.locale.ban_username_not_found)
                    return None
                user_id = cached_user.id
                expected_username = target[1:].casefold()
            else:
                await self._reply(update, context, update.locale.mute_user_not_found)
                return None
        else:
            reply = update.message.reply_to_message
            user = None if reply is None else self.telegram_helper.extract_message_user(reply)
            if user is None:
                await self._reply(update, context, update.locale.mute_user_not_found)
                return None
            user_id = user.id
        member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        if expected_username is not None and (member.user.username or "").casefold() != expected_username:
            await self._reply(update, context, update.locale.ban_username_changed)
            return None
        if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) or await self.state.is_admin(
                user_id, update.effective_chat.id):
            await self._reply(update, context, update.locale.durachok)
            return None
        if member.status in (ChatMemberStatus.BANNED, ChatMemberStatus.LEFT):
            await self._reply(update, context, update.locale.mute_not_member)
            return None
        if member.status == ChatMemberStatus.RESTRICTED and not member.is_member:
            await self._reply(update, context, update.locale.mute_not_member)
            return None
        return member.user

    async def _apply(
            self, update: EnrichedUpdate, context: CallbackContext, target: str | None,
            duration: int | None = None, duration_text: str | None = None,
    ) -> None:
        chat_id = update.effective_chat.id
        if update.effective_chat.type != ChatType.SUPERGROUP:
            await self._reply(update, context, update.locale.mute_supergroup_only)
            return
        try:
            user = await self._resolve_target(update, context, target)
            if user is None:
                return
            until_date = 0
            if duration is not None and duration <= 365 * 86400:
                # Round up to the whole seconds accepted by Telegram so that
                # timestamp truncation does not shorten the requested duration.
                until_date = ceil(time.time() + duration)
            result = await context.bot.restrict_chat_member(
                chat_id=chat_id, user_id=user.id,
                permissions=mute_permissions(duration is None),
                until_date=until_date,
                use_independent_chat_permissions=True,
            )
            if result is not True:
                raise TelegramError("Telegram did not confirm the restriction change")
        except TelegramError as error:
            self.logger.warning("Failed to change mute for %s in %s: %s", target, chat_id, error)
            template = update.locale.mute_failed if duration is not None else update.locale.unmute_failed
            await self._reply(update, context, template.format(error=str(error)))
            return

        user_link = self._user_link(user)
        template = update.locale.mute_success if duration is not None else update.locale.unmute_success
        await self.telegram_helper.send_message(
            context, chat_id, template.format(user=user_link, duration=duration_text),
        )
        await self._audit(update, context, user_link, target, duration_text)

    async def _audit(
            self, update: EnrichedUpdate, context: CallbackContext, user_link: str,
            target: str | None, duration_text: str | None,
    ) -> None:
        photo = None
        if target is None:
            reply = update.message.reply_to_message
            source = update.locale.mute_audit_reply.format(
                link=self.telegram_helper.build_message_link(reply),
            )
            photo = self.telegram_helper.extract_message_photo(reply)
        else:
            source = escape_markdown(target)
        template = (
            update.locale.audit_log_user_muted if duration_text is not None
            else update.locale.audit_log_user_unmuted
        )
        await self.telegram_helper.audit_log(
            context, update.message,
            template.format(
                user=user_link, moderator=self._user_link(update.effective_user),
                chat=escape_markdown(update.effective_chat.title or str(update.effective_chat.id)),
                chat_id=update.effective_chat.id, duration=duration_text, source=source,
            ), photo=photo,
        )

    @staticmethod
    def _user_link(user: User) -> str:
        return f"[{escape_markdown(user.full_name)}](tg://user?id={user.id}) ({user.id})"

    async def _reply(self, update: EnrichedUpdate, context: CallbackContext, text: str) -> None:
        await self.telegram_helper.send_message(
            context, update.effective_chat.id, text, parse_mode=None,
            reply_to_message_id=update.message.message_id,
        )
