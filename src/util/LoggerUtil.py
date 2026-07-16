import logging


class _TelegramApiStatusCheckLogFilter(logging.Filter):
    """Suppress routine APScheduler logs for the frequent Telegram API check."""

    _JOB_NAME = "telegram-api-status-check"

    def filter(self, record: logging.LogRecord) -> bool:
        if not record.name.startswith("apscheduler."):
            return True
        if record.levelno >= logging.WARNING:
            return True
        return self._JOB_NAME not in record.getMessage()


class LoggerUtil:
    __LOGGER_LEVELS = {
        # Scheduler DEBUG messages such as "Looking for jobs to run" do not
        # include a job name and therefore cannot be filtered per job.
        "apscheduler.scheduler": logging.INFO,
        "httpcore": logging.INFO,
        "httpx": logging.ERROR,
        "telegram": logging.INFO,
    }

    @staticmethod
    def get_logger(name: str, prefix: str) -> logging.Logger:
        """Get logger with the given name and prefix"""
        logging.basicConfig(
            format=LoggerUtil.get_default_format(prefix), level=logging.DEBUG
        )
        LoggerUtil.__configure_log_filters()
        for logger_name, level in LoggerUtil.__LOGGER_LEVELS.items():
            logging.getLogger(logger_name).setLevel(level)
        logger = logging.getLogger(name)
        return logger

    @staticmethod
    def __configure_log_filters() -> None:
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if any(
                isinstance(log_filter, _TelegramApiStatusCheckLogFilter)
                for log_filter in handler.filters
            ):
                continue
            handler.addFilter(_TelegramApiStatusCheckLogFilter())

    @staticmethod
    def get_default_format(prefix: str) -> str:
        return f"[{prefix}] %(asctime)s - %(name)s - %(levelname)s - %(message)s"
