from logging import Logger

from telegram import Update


class SpamFilter:

    def __init__(self, logger: Logger):
        self.logger = logger

    def is_spam(self, update: Update) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        pass

    @staticmethod
    def get_priority() -> int:
        """Returns the priority of this filter. Higher == run's first"""
        return 0
