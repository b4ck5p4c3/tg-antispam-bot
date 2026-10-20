import asyncio
import re
import time
from collections import deque
from datetime import timedelta

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter


class CoronerInterrupted(Exception):
    """A control command or membership event invalidated an in-flight check."""


class CoronerApi:
    """A paced sliding-minute budget shared by all Coroner calls, including UI."""

    def __init__(self, rpm, on_error, active=lambda: True):
        self._rpm = rpm
        self._on_error = on_error
        self._active = active
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
                   background=False, **params):
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
            if method.__name__ == "edit_message_text" and "message is not modified" in str(error).lower():
                return None
            self._on_error(error_chat_id, method.__name__, params, error, background)
            raise
        except Exception as error:
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
    def is_invalid_participant(error) -> bool:
        return isinstance(error, BadRequest) and str(error).strip().upper().removeprefix(
            "BAD REQUEST: ",
        ).strip() == "PARTICIPANT_ID_INVALID"

    @staticmethod
    def error_kind(error) -> str:
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
