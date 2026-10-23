from typing import NotRequired, TypedDict


class CommandHelpEntry(TypedDict):
    command: str
    locale_id: str
    menu_locale_id: NotRequired[str]
    aliases: NotRequired[tuple[str, ...]]
    admin: NotRequired[bool]


def command_help(*entries: CommandHelpEntry, module: str):
    """Describe command variants; module and locale_id refer to Locale fields.

    Use <name> for required arguments and [name] for optional arguments.
    aliases lists existing shortcuts; this decorator does not register commands.
    admin overrides the restriction inferred from @admin_command per variant.
    """
    def decorator(func):
        func.command_help = (module, entries)
        return func

    return decorator
