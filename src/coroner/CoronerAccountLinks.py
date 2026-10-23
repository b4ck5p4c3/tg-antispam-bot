import asyncio
import time
from dataclasses import dataclass, field
from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from src.coroner.CoronerApi import CoronerApi, CoronerInterrupted
from src.coroner.CoronerDisplay import account_label


@dataclass
class AccountLinksDisplay:
    chat_id: int
    message_id: int | None
    text: str
    rows: tuple[tuple[InlineKeyboardButton, ...], ...]
    t: Callable[[str], str]
    rejected: set[str] = field(default_factory=set)
    last_good: list[InlineKeyboardButton] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def key(self):
        return self.chat_id, self.message_id

    @property
    def links(self):
        return [button for row in self.rows for button in row if button.url]


class CoronerAccountLinks:
    """Isolate rejected account buttons without blocking Telegram update handling."""

    def __init__(self, service):
        self.service = service
        self._rejected = {}
        self._displays = {}

    def _bind(self, display):
        previous = self._displays.get(display.key)
        if previous is not None:
            display.lock = previous.lock
        self._displays[display.key] = display

    def _guard(self, display):
        if display.message_id is not None and self._displays.get(display.key) is not display:
            raise CoronerInterrupted()

    def _finish(self, display):
        if self._displays.get(display.key) is display:
            del self._displays[display.key]

    async def display(self, text, keyboard, t, chat_id, message_id=None, *, refresh=False):
        now = time.time()
        self._rejected = {key: until for key, until in self._rejected.items() if until > now}
        display = AccountLinksDisplay(chat_id, message_id, text, keyboard.inline_keyboard, t)
        for button in display.links:
            key = chat_id, button.url
            if refresh:
                self._rejected.pop(key, None)
            elif key in self._rejected:
                display.rejected.add(button.url)
        if message_id is not None:
            self._bind(display)
        links = [button for button in display.links if button.url not in display.rejected]
        background = False
        try:
            try:
                return await self._show(display, links)
            except TelegramError as error:
                if not links or not CoronerApi.is_profile_privacy_error(error):
                    raise
            message = await self._show(display, [], loading=True)
            # Let moderation updates and Stop run while account buttons are tested.
            self.service.application.create_task(self._resolve(display, links))
            background = True
            return message
        finally:
            if not background:
                self._finish(display)

    def _markup(self, display, links):
        allowed = {button.url for button in links}
        buttons = [button for button in display.links if button.url in allowed]
        columns = self.service.config.protection.account_links_per_row
        rows = [buttons[index:index + columns] for index in range(0, len(buttons), columns)]
        rows.extend([button for button in row if not button.url] for row in display.rows)
        return InlineKeyboardMarkup([row for row in rows if row])

    async def _show(self, display, links, *, loading=False, failed=False):
        text = display.text
        if loading:
            text += "\n\n" + display.t("account_links_loading")
        if failed:
            text += "\n\n" + display.t("account_links_failed")
        if display.rejected:
            ids = [button.text for button in display.links if button.url in display.rejected]
            text += "\n\n" + display.t("profile_buttons_unavailable") + "\n" + ", ".join(map(account_label, ids))
        params = dict(chat_id=display.chat_id, text=await self.service.display_text(text),
                      reply_markup=self._markup(display, links),
                      parse_mode="HTML", error_chat_id=display.chat_id)
        async with display.lock:
            self._guard(display)
            if display.message_id is None:
                method = self.service.bot.send_message
            else:
                method = self.service.bot.edit_message_text
                params["message_id"] = display.message_id
            message = await self.service.api.call(
                method, **params, expected_privacy_error=bool(links), guard=lambda: self._guard(display),
            )
            self._guard(display)
            if display.message_id is None:
                display.message_id = message.message_id
                self._bind(display)
            display.last_good = list(links)
            return message

    async def _probe(self, display, links, accepted, *, rejected=False):
        self._guard(display)
        if not rejected:
            try:
                await self._show(display, links, loading=True)
                accepted.extend(links)
                return
            except TelegramError as error:
                if not CoronerApi.is_profile_privacy_error(error):
                    raise
        self._guard(display)
        if len(links) == 1:
            button = links[0]
            display.rejected.add(button.url)
            self._rejected[display.chat_id, button.url] = (
                time.time() + self.service.config.protection.account_link_retry_seconds
            )
            return
        middle = len(links) // 2
        await self._probe(display, links[:middle], accepted)
        await self._probe(display, links[middle:], accepted)

    async def _resolve(self, display, links):
        try:
            # Retry once if privacy changes between a successful probe and assembly.
            for _ in range(2):
                accepted = []
                await self._probe(display, links, accepted, rejected=True)
                try:
                    await self._show(display, accepted)
                    return
                except TelegramError as error:
                    if not accepted or not CoronerApi.is_profile_privacy_error(error):
                        raise
                    links = accepted
            await self._show(display, display.last_good, failed=True)
        except CoronerInterrupted:
            pass
        except TelegramError:
            # The API wrapper records unexpected errors; expected rejections are shown in the page.
            try:
                await self._show(display, display.last_good, failed=True)
            except (TelegramError, CoronerInterrupted):
                pass
        except Exception as error:
            self.service._error(display.chat_id, "account-links", "worker_error", detail=error)
        finally:
            self._finish(display)
