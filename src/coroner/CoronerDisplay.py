import re
from html import escape


# Chat references stay structured until the final Telegram rendering step.
CHAT_REFERENCE = re.compile("\ue000(-?\\d+)\ue001")
DISPLAY_REFERENCE = re.compile(CHAT_REFERENCE.pattern + "|\ue002(\\d+)\ue003")


def chat_label(chat_id: int) -> str:
    return f"\ue000{chat_id}\ue001"


def account_label(user_id: str) -> str:
    return f"\ue002{user_id}\ue003"


def log_text(text: str) -> str:
    return CHAT_REFERENCE.sub(lambda match: match[1], text)


def render_html(text: str, titles: dict[int, str], limit: int = 4000) -> str:
    """Escape all text, format chat names, and respect Telegram's UTF-16 limit."""
    # Older view-level shortening may have cut a reference in the middle.
    text = re.sub("[\ue000\ue002][^\ue001\ue003]*$", "…", text)
    parts = []
    cursor = 0
    remaining = limit

    def append(value, code=False):
        nonlocal remaining
        size = len(value.encode("utf-16-le")) // 2
        if size > remaining:
            value = value.encode("utf-16-le")[:max(0, remaining - 1) * 2].decode("utf-16-le", errors="ignore") + "…"
            size = remaining
        if remaining:
            parts.append(f"<code>{escape(value)}</code>" if code else escape(value))
        remaining -= size

    for match in DISPLAY_REFERENCE.finditer(text):
        append(text[cursor:match.start()])
        append(titles[int(match[1])] if match[1] is not None else match[2], code=True)
        cursor = match.end()
        if not remaining:
            break
    else:
        append(text[cursor:])
    return "".join(parts)
