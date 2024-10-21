from telegram import Update
from telegram.ext import CallbackContext

from src.handlers.spam_filters.HTTPJsonSpamFilter import HTTPJsonSpamFilter


class LolsSpamFilter(HTTPJsonSpamFilter):
    __LOLS_API_URL = "https://api.lols.bot/account?id={id}"

    _name = "Lols"

    def _is_spam(self, update: Update, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        message_author_id = update.message.from_user.id
        request_url = self.__LOLS_API_URL.format(id=message_author_id)
        account_status = self.try_send_request(request_url, [200])
        if not account_status:
            return False
        self.logger.info(f"[{self._name}] User {message_author_id}: {account_status}")
        return account_status['banned']
