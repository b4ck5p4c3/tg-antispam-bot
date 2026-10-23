from html import escape

from telegram import BotCommand
from telegram.constants import ParseMode
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler
from src.handlers.CommandHelp import command_help
from src.locale.Locale import Locale
from src.telegram.EnrichedUpdate import EnrichedUpdate


class HelpCommandsHandler(BaseHandler):
    def __init__(self, state):
        super().__init__(state)
        self._modules = {}

    def register(self, handler) -> None:
        """Collect help only from callbacks registered with the application."""
        metadata = getattr(handler, "command_help", None)
        if metadata is None:
            return
        module, entries = metadata
        default_admin = getattr(handler, "admin_only", False)
        self._modules.setdefault(module, []).extend(
            (entry, entry.get("admin", default_admin)) for entry in entries
        )

    def render(self, locale: Locale) -> list[str]:
        messages = []
        text = escape(locale.help_legend)
        for module, entries in self._modules.items():
            heading = f"📌 <b>{escape(getattr(locale, module))}</b>"
            for index, (entry, admin) in enumerate(entries):
                command = entry["command"].lstrip("/")
                syntax = escape(f"/{command}")
                # Literal subcommands and <parameters> are mandatory arguments.
                if any(not token.startswith("[") for token in command.split()[1:]):
                    syntax = f"<code>{syntax}</code>"
                aliases = entry.get("aliases", ())
                if aliases:
                    syntax += f" ({escape(', '.join(aliases))})"
                lock = " 🔒" if admin else ""
                line = f"{syntax}{lock} — {escape(getattr(locale, entry['locale_id']))}"
                addition = f"\n\n{heading}\n{line}" if index == 0 else f"\n{line}"
                # Split on complete lines so HTML entities and tags stay intact.
                if len(text) + len(addition) > 3800:
                    messages.append(text)
                    text = f"{heading}\n{line}"
                else:
                    text += addition
        if text:
            messages.append(text)
        return messages

    def get_bot_commands(self, locale: Locale) -> list[BotCommand]:
        """Build Telegram's menu from the same metadata as /help.

        Telegram accepts only command names, without spaces or arguments.
        Keep one menu entry per root command, in help module order.
        """
        commands = {}
        for entries in self._modules.values():
            for entry, admin in entries:
                command = entry["command"].lstrip("/").split()[0]
                if command not in commands:
                    locale_id = entry.get("menu_locale_id", entry["locale_id"])
                    description = " ".join(getattr(locale, locale_id).split())
                    commands[command] = (description, admin)
                else:
                    description, all_admin = commands[command]
                    commands[command] = (description, all_admin and admin)
        return [
            BotCommand(command, (("🔒 " if admin else "") + description)[:256])
            for command, (description, admin) in commands.items()
        ]

    @command_help(
        {"command": "help", "locale_id": "help_command_info"},
        module="help_module_general",
    )
    async def handle_help(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        for text in self.render(update.locale):
            await self.telegram_helper.send_message(
                context, update.effective_chat.id, text,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=update.message.message_id,
            )
