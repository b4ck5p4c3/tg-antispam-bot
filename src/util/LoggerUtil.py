import logging


class LoggerUtil:
    __LOGGER_LEVELS = {
        "httpcore.http11": logging.INFO,
        "httpx": logging.ERROR,
    }

    @staticmethod
    def get_logger(name: str, prefix: str) -> logging.Logger:
        """Get logger with the given name and prefix"""
        logging.basicConfig(
            format=LoggerUtil.get_default_format(prefix), level=logging.DEBUG
        )
        for logger_name, level in LoggerUtil.__LOGGER_LEVELS.items():
            logging.getLogger(logger_name).setLevel(level)
        logger = logging.getLogger(name)
        return logger

    @staticmethod
    def get_default_format(prefix: str) -> str:
        return f"[{prefix}] %(asctime)s - %(name)s - %(levelname)s - %(message)s"
