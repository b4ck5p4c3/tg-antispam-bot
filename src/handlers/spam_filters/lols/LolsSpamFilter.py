from telegram import Update
from telegram.ext import CallbackContext

from src.handlers.spam_filters.HTTPJsonSpamFilter import HTTPJsonSpamFilter
from src.util.config.Config import Config


class LolsSpamFilter(HTTPJsonSpamFilter):
    __LOLS_API_URL = "https://api.lols.bot/account?id={id}"

    _filter_name = "Lols"

    def __init__(self, config: Config):
        super().__init__(config)

    async def _is_spam(self, update: Update, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        message_author_id = update.message.from_user.id
        return self.is_spam(message_author_id)

    def is_spam(self, user_id: int) -> bool:
        request_url = self.__LOLS_API_URL.format(id=user_id)
        account_status = self.try_send_request(request_url, [200])
        if not account_status:
            return False
        self.logger.info(f"User {user_id}: {account_status}")
        return account_status['banned']
