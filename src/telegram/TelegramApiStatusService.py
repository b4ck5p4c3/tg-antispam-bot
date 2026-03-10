import threading
from enum import StrEnum

from telegram.error import NetworkError, TelegramError
from telegram.ext import Application, ContextTypes, Job


class TelegramApiStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class TelegramApiStatusService:
    def __init__(self, check_interval_seconds: int = 10):
        self._status: TelegramApiStatus = TelegramApiStatus.UNAVAILABLE
        self._status_lock = threading.Lock()
        self._check_interval_seconds = check_interval_seconds
        self._job: Job | None = None

    def start(self, telegram_application: Application):
        if self._job is not None:
            return
        if telegram_application.job_queue is None:
            raise ValueError("Job queue is not configured")
        self._job = telegram_application.job_queue.run_repeating(
            callback=self._check_availability,
            interval=self._check_interval_seconds,
            first=0,
            name="telegram-api-status-check"
        )

    def stop(self):
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None

    def is_available(self) -> bool:
        with self._status_lock:
            return self._status == TelegramApiStatus.AVAILABLE

    def get_status(self) -> TelegramApiStatus:
        with self._status_lock:
            return self._status

    async def _check_availability(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            await context.application.bot.get_me()
            status = TelegramApiStatus.AVAILABLE
        except NetworkError:
            status = TelegramApiStatus.UNAVAILABLE
        except TelegramError:
            # Telegram API responded with a Telegram-level error, which still means connectivity is available.
            status = TelegramApiStatus.AVAILABLE
        except Exception:
            status = TelegramApiStatus.UNAVAILABLE
        with self._status_lock:
            self._status = status
