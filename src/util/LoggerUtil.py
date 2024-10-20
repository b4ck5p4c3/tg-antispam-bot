import logging


class LoggerUtil:

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """Get logger with the given name"""
        logging.basicConfig(
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
        )
        logger = logging.getLogger(name)
        return logger
