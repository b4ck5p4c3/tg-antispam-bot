#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import re
import shlex
import sys
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont

try:
    from telethon import TelegramClient, errors as telethon_errors, events, functions, utils
    from telethon.errors import RPCError
except ModuleNotFoundError:
    TelegramClient = None
    telethon_errors = None
    events = None
    functions = None
    utils = None
    RPCError = Exception


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "userbot_config.json"
DEFAULT_SESSION_PATH = SCRIPT_DIR / "userbot"
DEFAULT_LOG_PATH = SCRIPT_DIR / "userbot_debug.log"
BOT_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")
EVENT_BUFFER_SIZE = 500
DEFAULT_ANTISPAM_TEST_RAW_CHAT_ID = 2353726867
DEFAULT_ANTISPAM_TEST_CHAT_ID = -1002353726867
DEFAULT_ANTISPAM_SPAM_TEXT = "Помогу с финансами, пишите в личку. [mock:spam]"
DEFAULT_ANTISPAM_IMAGE_TEXT = "QUICK LOAN\nFINANCIAL HELP\nMESSAGE ME"
DEFAULT_ANTISPAM_CAPTION = "Быстрый заработок без опыта, подробности в личке. [mock:spam]"
DEFAULT_ANTISPAM_FORWARD_CAPTION = "Нужен человек на личном авто, оплата ежедневно. [mock:spam]"
DEFAULT_TEST_FONT_PATH = Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf")
DEFAULT_REJOIN_GRACE_SECONDS = 7


@dataclass
class UserbotConfig:
    api_id: int
    api_hash: str
    bot_username: str
    target_chat: str
    target_invite_link: str | None = None
    bot_dialog_started: bool = False
    raw_events: bool = False

    @classmethod
    def load_or_create(
            cls,
            path: Path,
            bot_username_override: str | None = None,
            target_chat_override: str | None = None,
            invite_link_override: str | None = None,
    ) -> UserbotConfig:
        stored_config = cls._load_json(path)
        stored_bot_username = stored_config.get("bot_username")

        api_id = os.getenv("TELETHON_API_ID") or stored_config.get("api_id")
        api_hash = os.getenv("TELETHON_API_HASH") or stored_config.get("api_hash")
        bot_username = (
            bot_username_override
            or os.getenv("ANTISPAM_BOT_USERNAME")
            or stored_config.get("bot_username")
        )
        explicit_target_chat = target_chat_override or os.getenv("ANTISPAM_TEST_CHAT")
        target_chat = explicit_target_chat or stored_config.get("target_chat")
        target_invite_link = (
            invite_link_override
            or os.getenv("ANTISPAM_TEST_CHAT_INVITE_LINK")
            or stored_config.get("target_invite_link")
        )

        if api_id is None:
            api_id = cls._prompt_api_id()
        else:
            api_id = cls._parse_api_id(api_id)
        if not api_hash:
            api_hash = getpass.getpass("Telegram API hash (my.telegram.org): ").strip()
        if not api_hash:
            raise ValueError("Telegram API hash cannot be empty")

        if not bot_username:
            bot_username = input("Bot username (for example, @my_antispam_bot): ").strip()
        bot_username = cls._normalize_bot_username(bot_username)
        bot_changed = (
            stored_bot_username is not None
            and cls._normalize_bot_username(stored_bot_username).lower() != bot_username.lower()
        )
        if bot_changed and explicit_target_chat is None:
            stored_bot_target = f"@{cls._normalize_bot_username(stored_bot_username)}"
            if str(target_chat).lower() in {stored_bot_target.lower(), stored_bot_target[1:].lower()}:
                target_chat = f"@{bot_username}"

        if target_chat is None:
            target_chat = input(
                f"Test chat username or ID (Enter for {DEFAULT_ANTISPAM_TEST_CHAT_ID}): "
            ).strip()
        target_chat = target_chat or str(DEFAULT_ANTISPAM_TEST_CHAT_ID)

        config = cls(
            api_id=api_id,
            api_hash=str(api_hash),
            bot_username=bot_username,
            target_chat=str(target_chat),
            target_invite_link=cls._normalize_invite_link(target_invite_link),
            bot_dialog_started=bool(stored_config.get("bot_dialog_started", False)) and not bot_changed,
            raw_events=bool(stored_config.get("raw_events", False)),
        )
        config.save(path)
        return config

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Failed to read {path}: {error}") from error
        if not isinstance(value, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        return value

    @staticmethod
    def _prompt_api_id() -> int:
        while True:
            value = input("Telegram API ID (my.telegram.org): ").strip()
            try:
                return UserbotConfig._parse_api_id(value)
            except ValueError as error:
                print(error)

    @staticmethod
    def _parse_api_id(value: Any) -> int:
        try:
            api_id = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Telegram API ID must be a positive integer") from error
        if api_id <= 0:
            raise ValueError("Telegram API ID must be a positive integer")
        return api_id

    @staticmethod
    def _normalize_bot_username(value: str) -> str:
        username = str(value).strip()
        username = username.removeprefix("https://t.me/").removeprefix("http://t.me/")
        username = username.removeprefix("@").rstrip("/")
        if not BOT_USERNAME_PATTERN.fullmatch(username):
            raise ValueError(f"Invalid bot username: {value!r}")
        if not username.lower().endswith("bot"):
            raise ValueError(f"Telegram bot username must end with 'bot': {value!r}")
        return username

    @staticmethod
    def _normalize_invite_link(value: Any) -> str | None:
        if value is None:
            return None
        invite_link = str(value).strip()
        return invite_link or None


@dataclass(frozen=True)
class ObservedEvent:
    sequence: int
    kind: str
    occurred_at: datetime
    chat_id: int | None
    message_id: int | None
    text: str
    raw: dict[str, Any]


class ScenarioError(ValueError):
    pass


class UserbotConsole:
    def __init__(
            self,
            client,
            config: UserbotConfig,
            config_path: Path,
            log_path: Path,
    ):
        self.client = client
        self.config = config
        self.config_path = config_path
        self.log_path = log_path
        self.logger = logging.getLogger("userbot")
        self.bot = None
        self.target = None
        self.bot_chat_id: int | None = None
        self.target_chat_id: int | None = None
        self.user_id: int | None = None
        self._sequence = 0
        self._events: deque[ObservedEvent] = deque(maxlen=EVENT_BUFFER_SIZE)
        self._event_condition = asyncio.Condition()

    async def initialize(self) -> None:
        me = await self.client.get_me()
        self.user_id = utils.get_peer_id(me)
        self.bot = await self.client.get_entity(f"@{self.config.bot_username}")
        if not getattr(self.bot, "bot", False):
            raise ValueError(f"@{self.config.bot_username} is not a Telegram bot")
        self.bot_chat_id = utils.get_peer_id(self.bot)

        try:
            self.target = await self.client.get_entity(self._parse_entity_ref(self.config.target_chat))
        except (RPCError, ValueError) as error:
            self.target = await self._try_join_configured_target()
            if self.target is None:
                print(f"Failed to resolve target {self.config.target_chat!r}: {error}")
                print("Falling back to the bot private chat. Use 'target <chat>' to change it.")
                self.target = self.bot
                self.config.target_chat = f"@{self.config.bot_username}"
                self.config.save(self.config_path)
        self.target_chat_id = utils.get_peer_id(self.target)

        self.client.add_event_handler(
            self._on_bot_message,
            events.NewMessage(from_users=self.bot),
        )
        self.client.add_event_handler(
            self._on_bot_message_edited,
            events.MessageEdited(from_users=self.bot),
        )
        self.client.add_event_handler(self._on_message_deleted, events.MessageDeleted())
        self.client.add_event_handler(self._on_chat_action, events.ChatAction())

        if not self.config.bot_dialog_started:
            try:
                await self.client.send_message(self.bot, "/start", parse_mode=None)
                self.config.bot_dialog_started = True
                self.config.save(self.config_path)
                self.logger.info("Started a private dialog with @%s", self.config.bot_username)
            except RPCError as error:
                self.logger.warning("Failed to start private bot dialog: %s", error)

        print(
            f"Authorized as {self._entity_label(me)}; bot=@{self.config.bot_username}; "
            f"target={self._entity_label(self.target)} ({self.target_chat_id})"
        )
        print(f"Debug log: {self.log_path}")

    async def repl(self) -> None:
        self.print_help()
        while True:
            try:
                line = (await asyncio.to_thread(input, "userbot> ")).strip()
            except EOFError:
                return
            if not line:
                continue
            try:
                should_exit = await self._execute_command(line)
                if should_exit:
                    return
            except (RPCError, ValueError) as error:
                self.logger.exception("Command failed")
                print(f"Command failed: {type(error).__name__}: {error}")

    async def run_subscription_scenario(self) -> None:
        print("Running subscription scenario: subscribe twice, list, unsubscribe twice.")
        steps = (
            ("subscribe", ("subscribed", "already subscribed")),
            ("subscribe", ("already subscribed",)),
            ("list", ("service notification subscribers",)),
            ("unsubscribe", ("unsubscribed",)),
            ("unsubscribe", ("not subscribed",)),
        )
        for action, expected_texts in steps:
            print(f"\n>>> /as_service {action}")
            response = await self.send_service_command(action)
            if response is None:
                raise ScenarioError(f"Subscription scenario failed on {action}: no bot response")
            response_text = response.text.lower()
            if not any(expected_text in response_text for expected_text in expected_texts):
                raise ScenarioError(
                    f"Subscription scenario failed on {action}: unexpected response {response.text!r}"
                )
        print("Subscription scenario passed.")

    async def run_watchdog_scenario(self, timeout: float) -> None:
        after_sequence = self._sequence
        print("Ensuring that this account is subscribed to service notifications...")
        await self.send_service_command("subscribe")
        print(
            "\nWaiting for an OpenAI outage notification in the bot private chat.\n"
            "For a quick test, run the bot with OPENAI_WATCHDOG_INTERVAL_SECONDS=5, "
            "then interrupt its OpenAI connection without restarting the bot."
        )
        try:
            outage = await self.wait_for_event(
                lambda item: (
                    item.kind == "NEW"
                    and item.chat_id == self.bot_chat_id
                    and "openai" in item.text.lower()
                    and ("unavailable" in item.text.lower() or "недоступ" in item.text.lower())
                ),
                after_sequence,
                timeout,
            )
        except TimeoutError:
            raise ScenarioError(
                f"No outage notification was received within {timeout:g} seconds"
            )

        print(
            f"Outage notification received (message {outage.message_id}). "
            "Restore OpenAI access without restarting the bot; waiting for the edit..."
        )
        try:
            recovery = await self.wait_for_event(
                lambda item: (
                    item.kind == "EDITED"
                    and item.chat_id == outage.chat_id
                    and item.message_id == outage.message_id
                ),
                outage.sequence,
                timeout,
            )
        except TimeoutError:
            raise ScenarioError(
                f"The outage notification was not edited within {timeout:g} seconds"
            )
        if not self._raw_contains_type(recovery.raw, "MessageEntityStrike"):
            raise ScenarioError("The recovery edit does not contain a strikethrough entity")
        recovery_text = recovery.text.lower()
        if "resolved" not in recovery_text and "устран" not in recovery_text:
            raise ScenarioError("The recovery edit does not contain a recovery signature")
        print("Watchdog scenario passed: the original notification was edited after recovery.")

    async def run_antispam_scenario(self, timeout: float, spam_text: str) -> None:
        await self._prepare_antispam_scenario(timeout)
        await self._run_antispam_case(
            "text only",
            lambda: self.send_text(spam_text),
            timeout,
        )
        print("Antispam scenario passed.")

    async def run_openai_message_types_scenario(
            self,
            timeout: float,
            selected_case: str = "all",
    ) -> None:
        await self._prepare_antispam_scenario(timeout)
        with TemporaryDirectory(prefix="tg-antispam-userbot-") as directory:
            image_path = Path(directory) / "spam.png"
            self._create_spam_image(image_path)
            all_cases: dict[str, tuple[str, Callable[[], Awaitable]]] = {
                "text": (
                    "text only",
                    lambda: self.send_text(DEFAULT_ANTISPAM_SPAM_TEXT),
                ),
                "image": (
                    "image only",
                    lambda: self.send_photo(image_path),
                ),
                "caption": (
                    "text and image",
                    lambda: self.send_photo(image_path, caption=DEFAULT_ANTISPAM_CAPTION),
                ),
                "forward": (
                    "forwarded text and image",
                    lambda: self.send_forwarded_photo(
                        image_path,
                        caption=DEFAULT_ANTISPAM_FORWARD_CAPTION,
                    ),
                ),
            }
            cases = (
                tuple(all_cases.values())
                if selected_case == "all"
                else (all_cases[selected_case],)
            )
            for index, (label, sender) in enumerate(cases, start=1):
                print(f"\n=== OpenAI media case {index}/{len(cases)}: {label} ===")
                await self._run_antispam_case(label, sender, timeout)
        print(f"OpenAI message-types scenario passed for selection: {selected_case}.")

    async def _prepare_antispam_scenario(self, timeout: float) -> None:
        if self.target_chat_id == self.bot_chat_id:
            raise ScenarioError("Antispam scenario requires a group target, not the bot private chat")
        await self._ensure_invite_link()

        permissions = await self._ensure_target_membership(timeout)
        await self._validate_configured_invite()
        if permissions.is_admin:
            raise ScenarioError(
                "Antispam scenario must be run by a non-admin account so the spam filter processes it"
            )
        if self._permissions_are_banned(permissions):
            raise ScenarioError("The userbot is currently banned from the target chat")

    async def _run_antispam_case(
            self,
            label: str,
            sender: Callable[[], Awaitable],
            timeout: float,
    ) -> None:
        after_sequence = self._sequence
        print(f"Sending spam case '{label}' from the non-admin account...")
        sent_message = await sender()

        try:
            await self.wait_for_event(
                lambda item: (
                    item.kind == "DELETED"
                    and item.chat_id == self.target_chat_id
                    and item.message_id == sent_message.id
                ),
                after_sequence,
                timeout,
            )
        except TimeoutError as error:
            raise ScenarioError(
                f"Case '{label}': the spam message was not deleted within {timeout:g} seconds"
            ) from error
        print(f"Case '{label}': the spam message was deleted.")

        try:
            restriction = await self.wait_for_event(
                lambda item: (
                    item.kind == "NEW"
                    and item.chat_id == self.target_chat_id
                    and (
                        "restricted" in item.text.lower()
                        or "огранич" in item.text.lower()
                    )
                ),
                after_sequence,
                timeout,
            )
        except TimeoutError as error:
            raise ScenarioError(
                f"Case '{label}': no restriction notification was received within {timeout:g} seconds"
            ) from error
        print(f"Case '{label}': restriction notification received (message {restriction.message_id}).")

        await self._wait_until_banned(timeout)
        print(f"Case '{label}': the account was banned. Waiting for the development-mode unban...")
        await self._rejoin_after_unban(timeout)
        print(f"Case '{label}' passed: the account was unbanned and rejoined.")

    async def send_service_command(self, action: str, timeout: float = 10) -> ObservedEvent | None:
        aliases = {
            "subscribe": "subscribe",
            "sub": "subscribe",
            "unsubscribe": "unsubscribe",
            "unsub": "unsubscribe",
            "list": "list",
            "ls": "list",
        }
        normalized_action = aliases.get(action.lower())
        if normalized_action is None:
            raise ValueError("Service action must be subscribe, unsubscribe, or list")
        return await self.send_and_wait_for_bot(
            self._bot_command("as_service", normalized_action),
            timeout=timeout,
        )

    async def send_and_wait_for_bot(
            self,
            text: str,
            reply_to: int | None = None,
            timeout: float = 10,
    ) -> ObservedEvent | None:
        after_sequence = self._sequence
        await self.send_text(text, reply_to=reply_to)
        try:
            return await self.wait_for_event(
                lambda item: item.kind == "NEW" and item.chat_id == self.target_chat_id,
                after_sequence,
                timeout,
            )
        except TimeoutError:
            print(
                f"No bot response in target chat within {timeout:g} seconds. "
                "Check that the account is an admin and inspect the bot logs."
            )
            return None

    async def send_text(self, text: str, reply_to: int | None = None):
        message = await self.client.send_message(
            self.target,
            text,
            reply_to=reply_to,
            parse_mode=None,
        )
        self.logger.info(
            "OUT chat=%s message=%s reply_to=%s text=%r",
            self.target_chat_id,
            message.id,
            reply_to,
            text,
        )
        print(f"SENT chat={self.target_chat_id} message={message.id}: {text}")
        return message

    async def send_photo(self, path: Path, caption: str | None = None):
        message = await self.client.send_file(
            self.target,
            path,
            caption=caption,
            force_document=False,
            parse_mode=None,
        )
        self.logger.info(
            "OUT PHOTO chat=%s message=%s caption=%r path=%s",
            self.target_chat_id,
            message.id,
            caption,
            path.name,
        )
        print(
            f"SENT PHOTO chat={self.target_chat_id} message={message.id}"
            f"{f' caption={caption}' if caption else ''}"
        )
        return message

    async def send_forwarded_photo(self, path: Path, caption: str):
        source = await self.client.send_file(
            self.bot,
            path,
            caption=caption,
            force_document=False,
            parse_mode=None,
        )
        try:
            forwarded = await self.client.forward_messages(
                self.target,
                source,
                from_peer=self.bot,
            )
        finally:
            await self.client.delete_messages(self.bot, source.id)
        if isinstance(forwarded, (list, tuple)):
            forwarded = forwarded[0]
        if getattr(forwarded, "fwd_from", None) is None:
            raise ScenarioError("Telegram sent a copy instead of a forwarded message")
        self.logger.info(
            "OUT FORWARD chat=%s message=%s source=%s caption=%r path=%s",
            self.target_chat_id,
            forwarded.id,
            source.id,
            caption,
            path.name,
        )
        print(
            f"SENT FORWARD chat={self.target_chat_id} message={forwarded.id} "
            f"source={source.id} caption={caption}"
        )
        return forwarded

    async def wait_for_event(
            self,
            predicate: Callable[[ObservedEvent], bool],
            after_sequence: int,
            timeout: float,
    ) -> ObservedEvent:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        async with self._event_condition:
            while True:
                for item in self._events:
                    if item.sequence > after_sequence and predicate(item):
                        return item
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                await asyncio.wait_for(self._event_condition.wait(), timeout=remaining)

    async def _execute_command(self, line: str) -> bool:
        command, _, arguments = line.partition(" ")
        command = command.lower()
        arguments = arguments.strip()

        if command in {"quit", "exit", "q"}:
            return True
        if command in {"help", "?"}:
            self.print_help()
        elif command == "status":
            await self.print_status()
        elif command == "service":
            if not arguments:
                raise ValueError("Usage: service subscribe|unsubscribe|list")
            await self.send_service_command(arguments)
        elif command == "scenario":
            await self._run_named_scenario(arguments)
        elif command == "spamtest":
            await self.run_antispam_scenario(90, arguments or DEFAULT_ANTISPAM_SPAM_TEXT)
        elif command == "openai-types":
            parts = shlex.split(arguments)
            timeout = self._parse_optional_float(parts[0] if parts else "", 90)
            selected_case = parts[1] if len(parts) == 2 else "all"
            if len(parts) > 2 or selected_case not in {"all", "text", "image", "caption", "forward"}:
                raise ValueError(
                    "Usage: openai-types [timeout] [all|text|image|caption|forward]"
                )
            await self.run_openai_message_types_scenario(timeout, selected_case)
        elif command == "send":
            if not arguments:
                raise ValueError("Usage: send <text>")
            await self.send_text(arguments)
        elif command == "reply":
            message_id, text = self._parse_reply_arguments(arguments)
            await self.send_text(text, reply_to=message_id)
        elif command == "report":
            message_id = self._parse_positive_int(arguments, "message ID")
            await self.send_and_wait_for_bot(self._bot_command("report"), reply_to=message_id)
        elif command == "target":
            if not arguments:
                print(f"Current target: {self._entity_label(self.target)} ({self.target_chat_id})")
            else:
                await self.set_target(arguments)
        elif command == "invite":
            self.set_invite_link(arguments)
        elif command == "dialogs":
            await self.print_dialogs(self._parse_optional_limit(arguments, 20))
        elif command == "history":
            await self.print_history(arguments)
        elif command == "watch":
            seconds = self._parse_optional_float(arguments, 60)
            print(f"Watching bot events for {seconds:g} seconds...")
            await asyncio.sleep(seconds)
        elif command == "raw":
            self.set_raw_events(arguments)
        elif command == "start":
            await self.client.send_message(self.bot, "/start", parse_mode=None)
            print("Sent /start to the bot private chat.")
        elif command.startswith("/"):
            await self.send_text(line)
        else:
            print("Unknown command. Enter 'help' to see available commands.")
        return False

    async def _run_named_scenario(self, arguments: str) -> None:
        parts = shlex.split(arguments)
        if not parts:
            raise ValueError(
                "Usage: scenario subscription | scenario watchdog [timeout] | "
                "scenario antispam [timeout] [spam text] | scenario openai-types [timeout]"
            )
        if parts[0] == "subscription" and len(parts) == 1:
            await self.run_subscription_scenario()
            return
        if parts[0] == "watchdog" and len(parts) <= 2:
            timeout = self._parse_optional_float(parts[1] if len(parts) == 2 else "", 300)
            await self.run_watchdog_scenario(timeout)
            return
        if parts[0] == "antispam":
            timeout = 90.0
            text_start = 1
            if len(parts) >= 2:
                try:
                    timeout = self._parse_optional_float(parts[1], timeout)
                    text_start = 2
                except ValueError:
                    pass
            spam_text = " ".join(parts[text_start:]) or DEFAULT_ANTISPAM_SPAM_TEXT
            await self.run_antispam_scenario(timeout, spam_text)
            return
        if parts[0] == "openai-types" and len(parts) <= 3:
            timeout = self._parse_optional_float(parts[1] if len(parts) >= 2 else "", 90)
            selected_case = parts[2] if len(parts) == 3 else "all"
            if selected_case not in {"all", "text", "image", "caption", "forward"}:
                raise ValueError(
                    "Usage: scenario openai-types [timeout] [all|text|image|caption|forward]"
                )
            await self.run_openai_message_types_scenario(timeout, selected_case)
            return
        raise ValueError(
            "Usage: scenario subscription | scenario watchdog [timeout] | "
            "scenario antispam [timeout] [spam text] | scenario openai-types [timeout]"
        )

    async def set_target(self, value: str) -> None:
        target = await self.client.get_entity(self._parse_entity_ref(value))
        self.target = target
        self.target_chat_id = utils.get_peer_id(target)
        self.config.target_chat = value
        self.config.save(self.config_path)
        print(f"Target changed to {self._entity_label(target)} ({self.target_chat_id})")

    def set_invite_link(self, value: str) -> None:
        if not value:
            state = "configured" if self.config.target_invite_link else "not configured"
            print(f"Target invite link is {state}.")
            return
        self._parse_invite_link(value)
        self.config.target_invite_link = UserbotConfig._normalize_invite_link(value)
        self.config.save(self.config_path)
        print("Target invite link saved.")

    async def print_status(self) -> None:
        me = await self.client.get_me()
        print(f"Account: {self._entity_label(me)} ({utils.get_peer_id(me)})")
        print(f"Bot: @{self.config.bot_username} ({self.bot_chat_id})")
        print(f"Target: {self._entity_label(self.target)} ({self.target_chat_id})")
        print(
            "Target invite link: "
            f"{'configured' if self.config.target_invite_link else 'not configured'}"
        )
        print(f"Connected: {self.client.is_connected()}")
        print(f"Raw event output: {'on' if self.config.raw_events else 'off'}")
        print(f"Config: {self.config_path}")
        print(f"Log: {self.log_path}")

    async def print_dialogs(self, limit: int) -> None:
        print("Recent dialogs:")
        async for dialog in self.client.iter_dialogs(limit=limit):
            print(f"  {utils.get_peer_id(dialog.entity):>14}  {dialog.name}")

    async def print_history(self, arguments: str) -> None:
        parts = shlex.split(arguments)
        source = "target"
        limit = 20
        if parts and parts[0] in {"target", "bot"}:
            source = parts.pop(0)
        if parts:
            limit = self._parse_positive_int(parts.pop(0), "history limit")
        if parts:
            raise ValueError("Usage: history [target|bot] [limit]")
        entity = self.bot if source == "bot" else self.target
        messages = await self.client.get_messages(entity, limit=limit)
        print(f"Last {len(messages)} messages from {source}:")
        for message in reversed(messages):
            sender = await message.get_sender()
            sender_label = self._entity_label(sender) if sender is not None else "unknown"
            text = message.raw_text or "<non-text message>"
            print(f"  id={message.id} from={sender_label}: {text!r}")
            self.logger.debug("HISTORY %s", self._json_dump(message.to_dict()))

    def set_raw_events(self, value: str) -> None:
        normalized = value.lower()
        if normalized not in {"on", "off"}:
            raise ValueError("Usage: raw on|off")
        self.config.raw_events = normalized == "on"
        self.config.save(self.config_path)
        print(f"Raw event output is now {normalized}.")

    async def _on_bot_message(self, event) -> None:
        await self._record_message_event("NEW", event)

    async def _on_bot_message_edited(self, event) -> None:
        await self._record_message_event("EDITED", event)

    async def _on_message_deleted(self, event) -> None:
        if event.chat_id not in {self.bot_chat_id, self.target_chat_id}:
            return
        raw = self._to_dict(event.original_update)
        for message_id in event.deleted_ids:
            await self._append_event(
                kind="DELETED",
                chat_id=event.chat_id,
                message_id=message_id,
                text="",
                raw=raw,
            )

    async def _on_chat_action(self, event) -> None:
        if event.chat_id != self.target_chat_id or self.user_id is None:
            return
        user_ids = set(getattr(event, "user_ids", None) or ())
        event_user_id = getattr(event, "user_id", None)
        if event_user_id is not None:
            user_ids.add(event_user_id)
        if self.user_id not in user_ids:
            return

        if event.user_kicked:
            kind = "KICKED"
        elif event.user_joined or event.user_added:
            kind = "JOINED"
        else:
            return
        await self._append_event(
            kind=kind,
            chat_id=event.chat_id,
            message_id=None,
            text="",
            raw=self._to_dict(event.original_update),
        )

    async def _record_message_event(self, kind: str, event) -> None:
        raw = self._to_dict(event.original_update)
        await self._append_event(
            kind=kind,
            chat_id=event.chat_id,
            message_id=event.message.id,
            text=event.raw_text or "<non-text message>",
            raw=raw,
        )

    async def _append_event(
            self,
            kind: str,
            chat_id: int | None,
            message_id: int | None,
            text: str,
            raw: dict[str, Any],
    ) -> None:
        async with self._event_condition:
            self._sequence += 1
            item = ObservedEvent(
                sequence=self._sequence,
                kind=kind,
                occurred_at=datetime.now(timezone.utc),
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                raw=raw,
            )
            self._events.append(item)
            self._event_condition.notify_all()

        timestamp = item.occurred_at.strftime("%H:%M:%S")
        print(f"\n[{timestamp}] EVENT {kind} chat={chat_id} message={message_id}")
        if text:
            print(f"  {text}")
        self.logger.info(
            "EVENT %s chat=%s message=%s text=%r",
            kind,
            chat_id,
            message_id,
            text,
        )
        self.logger.debug("RAW %s", self._json_dump(raw))
        if self.config.raw_events:
            print(self._json_dump(raw, indent=2))

    def _bot_command(self, name: str, arguments: str = "") -> str:
        suffix = f"@{self.config.bot_username}" if self.target_chat_id != self.bot_chat_id else ""
        command = f"/{name}{suffix}"
        return f"{command} {arguments}" if arguments else command

    @staticmethod
    def _parse_entity_ref(value: str) -> str | int:
        value = str(value).strip()
        if re.fullmatch(r"-?\d+", value):
            entity_id = int(value)
            if entity_id == DEFAULT_ANTISPAM_TEST_RAW_CHAT_ID:
                return DEFAULT_ANTISPAM_TEST_CHAT_ID
            return entity_id
        return value

    @staticmethod
    def _parse_reply_arguments(value: str) -> tuple[int, str]:
        message_id_text, separator, text = value.partition(" ")
        if not separator or not text.strip():
            raise ValueError("Usage: reply <message_id> <text>")
        return UserbotConsole._parse_positive_int(message_id_text, "message ID"), text.strip()

    @staticmethod
    def _parse_positive_int(value: str, label: str) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a positive integer") from error
        if parsed <= 0:
            raise ValueError(f"{label} must be a positive integer")
        return parsed

    @staticmethod
    def _parse_optional_limit(value: str, default: int) -> int:
        return default if not value else UserbotConsole._parse_positive_int(value, "limit")

    @staticmethod
    def _parse_optional_float(value: str, default: float) -> float:
        if not value:
            return default
        try:
            parsed = float(value)
        except ValueError as error:
            raise ValueError("Timeout must be a positive number") from error
        if parsed <= 0:
            raise ValueError("Timeout must be a positive number")
        return parsed

    @staticmethod
    def _entity_label(entity) -> str:
        if entity is None:
            return "unknown"
        username = getattr(entity, "username", None)
        if username:
            return f"@{username}"
        title = getattr(entity, "title", None)
        if title:
            return title
        name = " ".join(
            value for value in (
                getattr(entity, "first_name", None),
                getattr(entity, "last_name", None),
            ) if value
        )
        return name or str(getattr(entity, "id", "unknown"))

    @staticmethod
    def _to_dict(value) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            return value.to_dict()
        return {"value": str(value)}

    @staticmethod
    def _json_dump(value: Any, indent: int | None = None) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, indent=indent)

    @staticmethod
    def _raw_contains_type(value: Any, expected_type: str) -> bool:
        if isinstance(value, dict):
            return any(
                item == expected_type or UserbotConsole._raw_contains_type(item, expected_type)
                for item in value.values()
            )
        if isinstance(value, (list, tuple)):
            return any(UserbotConsole._raw_contains_type(item, expected_type) for item in value)
        return False

    async def _ensure_invite_link(self) -> None:
        if self.config.target_invite_link:
            return
        target_username = getattr(self.target, "username", None)
        if target_username:
            self.set_invite_link(f"@{target_username}")
            return
        try:
            invite_link = (
                await asyncio.to_thread(
                    input,
                    "Invite link used to rejoin the test chat after unban: ",
                )
            ).strip()
        except EOFError as error:
            raise ScenarioError(
                "An invite link is required; pass it with --invite-link or "
                "ANTISPAM_TEST_CHAT_INVITE_LINK"
            ) from error
        if not invite_link:
            raise ScenarioError("An invite link is required for the antispam scenario")
        self.set_invite_link(invite_link)

    async def _wait_until_banned(self, timeout: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            if await self._is_current_user_banned():
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ScenarioError(
                    f"The account was not banned within {timeout:g} seconds. "
                    "Start the bot with --development to shorten the moderation delay."
                )
            await asyncio.sleep(min(1, remaining))

    async def _rejoin_after_unban(self, timeout: float) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last_error: Exception | None = None
        await asyncio.sleep(min(DEFAULT_REJOIN_GRACE_SECONDS, timeout))
        while True:
            try:
                target = await self._join_configured_target()
                if target is not None:
                    self.target = target
                    self.target_chat_id = utils.get_peer_id(target)
                    if not await self._is_current_user_banned():
                        return
            except (
                telethon_errors.UserBannedInChannelError,
                telethon_errors.ChannelPrivateError,
                telethon_errors.InviteHashExpiredError,
                telethon_errors.InviteHashInvalidError,
            ) as error:
                last_error = error
            except telethon_errors.FloodWaitError as error:
                last_error = error
                remaining = deadline - loop.time()
                wait_seconds = error.seconds + 1
                if wait_seconds >= remaining:
                    raise ScenarioError(
                        f"Telegram requires waiting {error.seconds} seconds before rejoining, "
                        f"which exceeds the remaining scenario timeout"
                    ) from error
                print(f"Telegram requested a {error.seconds}-second wait before the next join attempt.")
                await asyncio.sleep(wait_seconds)
            except telethon_errors.InviteRequestSentError as error:
                raise ScenarioError(
                    "The invite link requires administrator approval, so automatic rejoin is impossible"
                ) from error

            remaining = deadline - loop.time()
            if remaining <= 0:
                detail = f": {last_error}" if last_error is not None else ""
                raise ScenarioError(
                    f"Failed to rejoin the chat within {timeout:g} seconds{detail}. "
                    "Make sure the bot is running with --development."
                )
            await asyncio.sleep(min(2, remaining))

    async def _is_current_user_banned(self) -> bool:
        try:
            permissions = await self.client.get_permissions(self.target, "me")
        except (
            telethon_errors.UserNotParticipantError,
            telethon_errors.ChannelPrivateError,
        ):
            return True
        return self._permissions_are_banned(permissions)

    async def _ensure_target_membership(self, timeout: float):
        try:
            return await self.client.get_permissions(self.target, "me")
        except (
            telethon_errors.UserNotParticipantError,
            telethon_errors.ChannelPrivateError,
        ):
            try:
                target = await self._join_configured_target_after_flood_wait(timeout)
            except (
                telethon_errors.UserBannedInChannelError,
                telethon_errors.ChannelPrivateError,
            ) as error:
                raise ScenarioError("The userbot is currently banned from the target chat") from error
            self.target = target
            self.target_chat_id = utils.get_peer_id(target)
            return await self.client.get_permissions(self.target, "me")

    async def _join_configured_target_after_flood_wait(self, timeout: float):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                return await self._join_configured_target()
            except telethon_errors.FloodWaitError as error:
                remaining = deadline - loop.time()
                wait_seconds = error.seconds + 1
                if wait_seconds >= remaining:
                    raise ScenarioError(
                        f"Telegram requires waiting {error.seconds} seconds before joining, "
                        f"which exceeds the scenario timeout"
                    ) from error
                print(f"Telegram requested a {error.seconds}-second wait before joining the test chat.")
                await asyncio.sleep(wait_seconds)

    async def _validate_configured_invite(self) -> None:
        invite_link = self.config.target_invite_link
        if not invite_link:
            raise ScenarioError("No target invite link is configured")
        invite_kind, invite_value = self._parse_invite_link(invite_link)
        try:
            if invite_kind == "public":
                target = await self.client.get_entity(invite_value)
            else:
                invite = await self.client(functions.messages.CheckChatInviteRequest(invite_value))
                target = getattr(invite, "chat", None)
                if target is None:
                    raise ScenarioError(
                        "The private invite link cannot be matched to the configured target"
                    )
            self._validate_target_chat(target)
        except (
            telethon_errors.InviteHashExpiredError,
            telethon_errors.InviteHashInvalidError,
        ) as error:
            raise ScenarioError("The configured invite link is invalid or expired") from error

    @staticmethod
    def _permissions_are_banned(permissions) -> bool:
        participant = getattr(permissions, "participant", None)
        banned_rights = getattr(participant, "banned_rights", None)
        return bool(banned_rights is not None and banned_rights.view_messages)

    async def _try_join_configured_target(self):
        if not self.config.target_invite_link:
            return None
        try:
            return await self._join_configured_target()
        except (
            telethon_errors.UserAlreadyParticipantError,
            telethon_errors.UserBannedInChannelError,
            telethon_errors.ChannelPrivateError,
            telethon_errors.InviteHashExpiredError,
            telethon_errors.InviteHashInvalidError,
            telethon_errors.InviteRequestSentError,
        ) as error:
            self.logger.warning(
                "Failed to join the configured target using its invite link: %s",
                type(error).__name__,
            )
            return None

    async def _join_configured_target(self):
        invite_link = self.config.target_invite_link
        if not invite_link:
            raise ScenarioError("No target invite link is configured")
        if self.target is not None:
            try:
                self._validate_target_chat(self.target)
                await self.client(functions.channels.JoinChannelRequest(self.target))
                return self.target
            except telethon_errors.UserAlreadyParticipantError:
                return self.target
            except telethon_errors.UserBannedInChannelError:
                raise
            except (telethon_errors.ChannelPrivateError, ValueError):
                pass

        invite_kind, invite_value = self._parse_invite_link(invite_link)
        try:
            if invite_kind == "hash":
                result = await self.client(functions.messages.ImportChatInviteRequest(invite_value))
                updates = getattr(result, "updates", result)
                target = self._find_target_chat(getattr(updates, "chats", ()))
                if target is not None:
                    return target
            else:
                target = await self.client.get_entity(invite_value)
                await self.client(functions.channels.JoinChannelRequest(target))
                self._validate_target_chat(target)
                return target
        except telethon_errors.UserAlreadyParticipantError:
            pass
        target = await self.client.get_entity(self._parse_entity_ref(self.config.target_chat))
        self._validate_target_chat(target)
        return target

    def _find_target_chat(self, chats):
        expected_chat_id = self._parse_entity_ref(self.config.target_chat)
        for chat in chats:
            chat_id = utils.get_peer_id(chat)
            if not isinstance(expected_chat_id, int) or chat_id == expected_chat_id:
                return chat
        if chats:
            raise ScenarioError("The invite link points to a different chat than the configured target")
        return None

    def _validate_target_chat(self, target) -> None:
        expected_chat_id = self._parse_entity_ref(self.config.target_chat)
        if isinstance(expected_chat_id, int) and utils.get_peer_id(target) != expected_chat_id:
            raise ScenarioError("The invite link points to a different chat than the configured target")

    @staticmethod
    def _create_spam_image(path: Path) -> None:
        image = Image.new("RGB", (1400, 800), "white")
        draw = ImageDraw.Draw(image)
        font_path = DEFAULT_TEST_FONT_PATH
        if not font_path.exists():
            raise ScenarioError(f"Test font is unavailable: {font_path}")
        font = ImageFont.truetype(str(font_path), 96)
        text_box = draw.multiline_textbbox(
            (0, 0),
            DEFAULT_ANTISPAM_IMAGE_TEXT,
            font=font,
            spacing=36,
            align="center",
        )
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        position = ((image.width - text_width) // 2, (image.height - text_height) // 2)
        draw.multiline_text(
            position,
            DEFAULT_ANTISPAM_IMAGE_TEXT,
            fill="black",
            font=font,
            spacing=36,
            align="center",
        )
        image.save(path, format="PNG")

    @staticmethod
    def _parse_invite_link(value: str) -> tuple[str, str]:
        invite_link = value.strip()
        if invite_link.startswith("tg://"):
            parsed = urlparse(invite_link)
            invite_hash = parse_qs(parsed.query).get("invite", [None])[0]
            if parsed.netloc == "join" and invite_hash:
                return "hash", invite_hash
            raise ValueError("Unsupported Telegram invite link")

        normalized = invite_link
        if normalized.startswith("@"):
            return "public", normalized
        if "://" not in normalized:
            normalized = f"https://{normalized}"
        parsed = urlparse(normalized)
        if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
            raise ValueError("Invite link must point to t.me")
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) == 1 and path_parts[0].startswith("+"):
            invite_hash = path_parts[0][1:]
            if invite_hash:
                return "hash", invite_hash
            raise ValueError("Telegram invite hash cannot be empty")
        if len(path_parts) == 2 and path_parts[0].lower() == "joinchat":
            return "hash", path_parts[1]
        if len(path_parts) == 1:
            return "public", path_parts[0]
        raise ValueError("Unsupported Telegram invite link")

    @staticmethod
    def print_help() -> None:
        print(
            """
Commands:
  service subscribe|unsubscribe|list  Manage service notification subscription
  scenario subscription              Test subscribe/list/unsubscribe and idempotency
  scenario watchdog [timeout]        Wait for outage notification and recovery edit
  scenario antispam [timeout] [text] Test delete, restrict, ban, unban, and rejoin
  scenario openai-types [timeout] [case]
                                      Test all types or one selected case
  spamtest [text]                     Run the antispam scenario with a 90-second timeout
  openai-types [timeout] [case]       Run all types or text|image|caption|forward
  send <text>                         Send arbitrary text to the target chat
  reply <message_id> <text>           Reply to a message in the target chat
  report <message_id>                 Send /report as a reply to a target message
  /command [arguments]                Send an arbitrary bot command to the target chat
  target [username|ID]                Show or change the target chat
  invite [link]                       Show or set the target chat invite link
  dialogs [limit]                     List recent dialogs and their IDs
  history [target|bot] [limit]        Show recent messages
  watch [seconds]                     Keep listening without accepting input
  raw on|off                          Toggle raw Telegram updates in the console
  status                              Show current account, bot, target, and paths
  start                               Send /start in the bot private chat
  help                                Show this help
  quit                                Disconnect and exit
""".strip()
        )


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)
    logging.getLogger("asyncio").setLevel(logging.INFO)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive Telethon userbot for antispam bot debugging")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Local JSON config path")
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION_PATH, help="Telethon session path")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH, help="Debug log path")
    parser.add_argument("--bot", help="Override the configured bot username")
    parser.add_argument("--target", help="Override the configured test chat username or ID")
    parser.add_argument(
        "--invite-link",
        help="Invite link used to rejoin the target after a development-mode unban",
    )
    parser.add_argument("--raw", action="store_true", help="Print raw Telegram updates")
    parser.add_argument(
        "--scenario",
        choices=("interactive", "subscription", "watchdog", "antispam", "openai-types"),
        default="interactive",
        help="Run interactively or execute one scenario",
    )
    parser.add_argument(
        "--watchdog-timeout",
        type=float,
        default=300,
        help="Timeout for each watchdog scenario stage",
    )
    parser.add_argument(
        "--antispam-timeout",
        type=float,
        default=90,
        help="Timeout for each antispam scenario stage",
    )
    parser.add_argument(
        "--spam-text",
        default=DEFAULT_ANTISPAM_SPAM_TEXT,
        help="Spam text sent by the antispam scenario",
    )
    parser.add_argument(
        "--openai-case",
        choices=("all", "text", "image", "caption", "forward"),
        default="all",
        help="Run all OpenAI message types or one selected case",
    )
    return parser


async def run(args: argparse.Namespace) -> None:
    config_path = args.config.expanduser().resolve()
    session_path = args.session.expanduser().resolve()
    log_path = args.log.expanduser().resolve()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    configure_logging(log_path)

    config = UserbotConfig.load_or_create(
        config_path,
        bot_username_override=args.bot,
        target_chat_override=args.target,
        invite_link_override=args.invite_link,
    )
    if args.raw:
        config.raw_events = True
        config.save(config_path)

    client = TelegramClient(str(session_path), config.api_id, config.api_hash)
    await client.start()
    console = UserbotConsole(client, config, config_path, log_path)
    try:
        await console.initialize()
        if args.scenario == "subscription":
            await console.run_subscription_scenario()
        elif args.scenario == "watchdog":
            await console.run_watchdog_scenario(args.watchdog_timeout)
        elif args.scenario == "antispam":
            await console.run_antispam_scenario(args.antispam_timeout, args.spam_text)
        elif args.scenario == "openai-types":
            await console.run_openai_message_types_scenario(
                args.antispam_timeout,
                args.openai_case,
            )
        else:
            await console.repl()
    finally:
        await client.disconnect()


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    if TelegramClient is None:
        parser.error("Telethon is not installed. Run: pip install -r dev/requirements.txt")
    if args.watchdog_timeout <= 0:
        parser.error("--watchdog-timeout must be positive")
    if args.antispam_timeout <= 0:
        parser.error("--antispam-timeout must be positive")
    if not args.spam_text.strip():
        parser.error("--spam-text cannot be empty")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except (RPCError, ValueError, OSError) as error:
        logging.getLogger("userbot").exception("Userbot stopped")
        print(f"Userbot stopped: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
