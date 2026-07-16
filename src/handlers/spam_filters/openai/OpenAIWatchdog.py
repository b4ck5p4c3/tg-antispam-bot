import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum

import httpx
from openai import AsyncOpenAI
from telegram.ext import Application, CallbackContext, Job

from src.handlers.ServiceNotificationsHandler import ServiceNotificationsHandler
from src.handlers.spam_filters.openai.OpenAIConfig import OpenAIFilterConfig
from src.util.LoggerUtil import LoggerUtil


class OpenAIIncidentStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"


@dataclass
class OpenAIIncident:
    error: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: OpenAIIncidentStatus = OpenAIIncidentStatus.ACTIVE
    resolved_at: datetime | None = None
    notifications: dict[int, int] = field(default_factory=dict)


class OpenAIUnavailableError(Exception):
    pass


class OpenAIWatchdog:
    _DEFAULT_CHECK_INTERVAL_SECONDS = int(timedelta(hours=1).total_seconds())
    _REQUEST_TIMEOUT_SECONDS = 30
    _MAX_ERROR_TEXT_LENGTH = 3000

    def __init__(self, config: OpenAIFilterConfig, notifications_handler: ServiceNotificationsHandler):
        self.config = config
        self.notifications_handler = notifications_handler
        self.logger = LoggerUtil.get_logger("ServiceWatchdog", "OpenAI")
        self.incidents: list[OpenAIIncident] = []
        self._incident_lock = asyncio.Lock()
        self._job: Job | None = None
        self._client = self._create_client()
        self._check_interval_seconds = self._get_check_interval_seconds()

    def start(self, application: Application) -> None:
        if self._job is not None:
            return
        if application.job_queue is None:
            raise ValueError("Job queue is not configured")
        self._job = application.job_queue.run_repeating(
            callback=self._check_availability,
            interval=self._check_interval_seconds,
            first=1,
            name="openai-availability-check",
        )

    async def analyze_message(self, context: CallbackContext, message: str) -> str | None:
        return await self._execute_monitored_request(
            context,
            lambda: self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "text",
                                "text": self.config.get_prompt(),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": message,
                            }
                        ],
                    },
                ],
                temperature=self.config.prompt_config.temperature,
                max_tokens=self.config.prompt_config.max_tokens,
                top_p=self.config.prompt_config.top_p,
                frequency_penalty=self.config.prompt_config.frequency_penalty,
                presence_penalty=self.config.prompt_config.presence_penalty,
                response_format={"type": "text"},
            ),
        )

    async def _check_availability(self, context: CallbackContext) -> None:
        await self._execute_monitored_request(
            context,
            lambda: self._client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": "Say pong."}],
                temperature=0,
                max_tokens=1,
            ),
        )

    async def _execute_monitored_request(
            self,
            context: CallbackContext,
            request: Callable[[], Awaitable],
    ) -> str | None:
        try:
            if self._client is None:
                raise OpenAIUnavailableError("OPENAI_API_KEY is not configured")
            response = await request()
            answer = self._extract_answer(response)
        except Exception as error:
            self.logger.error(f"OpenAI request failed: {type(error).__name__}: {error}")
            await self._record_failure(context, error)
            return None

        await self._record_success(context)
        return answer

    async def _record_failure(self, context: CallbackContext, error: Exception) -> None:
        async with self._incident_lock:
            if self._get_active_incident() is not None:
                return

            error_text = self._format_error(error)
            incident = OpenAIIncident(error=error_text)
            self.incidents.append(incident)
            incident.notifications = await self.notifications_handler.notify_openai_unavailable(context, error_text)

    async def _record_success(self, context: CallbackContext) -> None:
        async with self._incident_lock:
            incident = self._get_active_incident()
            if incident is None:
                return

            incident.status = OpenAIIncidentStatus.RESOLVED
            incident.resolved_at = datetime.now(timezone.utc)
            await self.notifications_handler.notify_openai_recovered(
                context,
                incident.error,
                incident.resolved_at,
                incident.notifications,
            )
            self.logger.info(f"OpenAI incident from {incident.started_at.isoformat()} was resolved")

    def _get_active_incident(self) -> OpenAIIncident | None:
        if len(self.incidents) == 0:
            return None
        latest_incident = self.incidents[-1]
        if latest_incident.status == OpenAIIncidentStatus.ACTIVE:
            return latest_incident
        return None

    def _create_client(self) -> AsyncOpenAI | None:
        token = os.environ.get("OPENAI_API_KEY")
        if not token:
            self.logger.warning("OPENAI_API_KEY is not set. OpenAI filtering is disabled")
            return None

        client_kwargs = {
            "api_key": token,
            "timeout": self._REQUEST_TIMEOUT_SECONDS,
        }
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            client_kwargs["base_url"] = base_url

        proxy_url = os.environ.get("OPENAI_PROXY_URL")
        if proxy_url is None or proxy_url == "":
            return AsyncOpenAI(**client_kwargs)
        return AsyncOpenAI(
            **client_kwargs,
            http_client=httpx.AsyncClient(proxy=proxy_url),
        )

    @staticmethod
    def _extract_answer(response) -> str:
        if response is None or len(response.choices) == 0:
            raise OpenAIUnavailableError("OpenAI returned an empty response")
        answer = response.choices[0].message.content
        if answer is None or answer.strip() == "":
            raise OpenAIUnavailableError("OpenAI returned a response without text")
        return answer

    def _format_error(self, error: Exception) -> str:
        error_text = f"{type(error).__name__}: {error}"
        if len(error_text) <= self._MAX_ERROR_TEXT_LENGTH:
            return error_text
        return f"{error_text[:self._MAX_ERROR_TEXT_LENGTH]}…"

    def _get_check_interval_seconds(self) -> int:
        configured_value = os.getenv("OPENAI_WATCHDOG_INTERVAL_SECONDS")
        if configured_value is None:
            return self._DEFAULT_CHECK_INTERVAL_SECONDS
        try:
            interval_seconds = int(configured_value)
        except ValueError:
            self.logger.warning(
                "Invalid OPENAI_WATCHDOG_INTERVAL_SECONDS=%r, using %s seconds",
                configured_value,
                self._DEFAULT_CHECK_INTERVAL_SECONDS,
            )
            return self._DEFAULT_CHECK_INTERVAL_SECONDS
        if interval_seconds <= 0:
            self.logger.warning(
                "OPENAI_WATCHDOG_INTERVAL_SECONDS must be positive, using %s seconds",
                self._DEFAULT_CHECK_INTERVAL_SECONDS,
            )
            return self._DEFAULT_CHECK_INTERVAL_SECONDS
        return interval_seconds
