import asyncio
import logging
import re
import time
from collections import deque
from datetime import timedelta

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError


class CoronerInterrupted(Exception):
    """A control command or membership event invalidated an in-flight check."""


class CoronerApi:
    """A paced sliding-minute budget shared by all Coroner calls, including UI."""

    _RETRYABLE_METHODS = frozenset((
        "get_chat_member", "get_chat", "get_chat_member_count", "get_chat_administrators",
        "answer_callback_query",
    ))

    def __init__(self, rpm, on_error, active=lambda: True,
                 invalid_response_retries=lambda: 1, invalid_response_retry_delay=lambda: 1):
        self._rpm = rpm
        self._on_error = on_error
        self._active = active
        self._invalid_response_retries = invalid_response_retries
        self._invalid_response_retry_delay = invalid_response_retry_delay
        self._condition = asyncio.Condition()
        self._calls = deque()
        self._waiters = []
        self._sequence = 0
        self._next_at = 0.0
        self._blocked_until = 0.0

    async def _acquire(self, priority: int, guard=None):
        async with self._condition:
            self._sequence += 1
            waiter = (priority, self._sequence, time.monotonic())
            self._waiters.append(waiter)
            try:
                while True:
                    if not self._active():
                        raise CoronerInterrupted()
                    if guard is not None:
                        guard()
                    now = time.monotonic()
                    while self._calls and self._calls[0] <= now - 60:
                        self._calls.popleft()
                    # Age waiting calls so an active status UI cannot starve checks.
                    first = min(self._waiters, key=lambda item: (
                        item[0] - int((now - item[2]) / 5), item[1],
                    ))
                    rpm = self._rpm()
                    ready_at = max(self._next_at, self._blocked_until)
                    if len(self._calls) >= rpm:
                        ready_at = max(ready_at, self._calls[-rpm] + 60)
                    if first == waiter and ready_at <= now:
                        self._calls.append(now)
                        self._next_at = now + 60 / rpm
                        return
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(), timeout=min(1, max(0.01, ready_at - now)),
                        )
                    except TimeoutError:
                        pass
            finally:
                self._waiters.remove(waiter)
                self._condition.notify_all()

    async def call(self, method, *, priority=0, guard=None, error_chat_id=None,
                   background=False, expected_privacy_error=False, **params):
        retries = self._invalid_response_retries() if method.__name__ in self._RETRYABLE_METHODS else 0
        for attempt in range(retries + 1):
            await self._acquire(priority, guard)
            if not self._active():
                raise CoronerInterrupted()
            if guard is not None:
                guard()
            try:
                return await method(
                    **params, read_timeout=15, write_timeout=15,
                    connect_timeout=5, pool_timeout=5,
                )
            except BadRequest as error:
                if (background and method.__name__ in ("get_chat_member", "get_chat")
                        and self.is_missing_member(error) and guard is not None):
                    guard()  # A late negative result must not invalidate a newer join or message.
                if method.__name__ == "edit_message_text" and "message is not modified" in str(error).lower():
                    return None
                if not (expected_privacy_error and self.is_profile_privacy_error(error)):
                    self._on_error(error_chat_id, method.__name__, params, error, background)
                raise
            except Exception as error:
                if self.is_invalid_response(error) and attempt < retries:
                    logging.getLogger("Coroner").warning(
                        "CORONER invalid API/proxy response for %s; retry=%s/%s",
                        method.__name__, attempt + 1, retries,
                    )
                    await asyncio.sleep(self._invalid_response_retry_delay())
                    continue
                if isinstance(error, RetryAfter):
                    seconds = self.retry_delay(error)
                    self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)
                self._on_error(error_chat_id, method.__name__, params, error, background)
                raise

    @staticmethod
    def retry_delay(error, default=60) -> float:
        if isinstance(error, RetryAfter):
            value = error.retry_after
            return value.total_seconds() if isinstance(value, timedelta) else float(value)
        return default

    @staticmethod
    def is_profile_privacy_error(error) -> bool:
        return isinstance(error, BadRequest) and "BUTTON_USER_PRIVACY_RESTRICTED" in str(error).upper()

    @staticmethod
    def is_missing_member(error) -> bool:
        if not isinstance(error, BadRequest):
            return False
        reason = str(error).strip().casefold().removeprefix("bad request: ").strip().replace("_", " ")
        return reason in {"member not found", "user not found", "participant id invalid", "user id invalid"}

    @staticmethod
    def is_invalid_response(error) -> bool:
        if not isinstance(error, TelegramError):
            return False
        # Recent PTB versions wrap this parsing error in NetworkError for HTTP 5xx.
        for _ in range(4):
            if error is None:
                return False
            if str(error).strip().casefold() == "invalid server response":
                return True
            error = error.__cause__
        return False

    @staticmethod
    def error_kind(error) -> str:
        if CoronerApi.is_invalid_response(error):
            return "api_invalid_response"
        if isinstance(error, Forbidden):
            return "api_forbidden"
        if isinstance(error, RetryAfter):
            return "api_retry"
        if isinstance(error, NetworkError) and not isinstance(error, BadRequest):
            return "api_network"
        if isinstance(error, BadRequest):
            return "api_bad_request"
        return "api_other"

    @staticmethod
    def safe_detail(error) -> str:
        return re.sub(r"\b\d{5,}:[A-Za-z0-9_-]{15,}\b", "[REDACTED]", str(error))[:1000]
