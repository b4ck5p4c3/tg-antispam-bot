from telegram import Update

from modules.HTTPJsonSpamFilter import HTTPJsonSpamFilter


class LolsSpamFilter(HTTPJsonSpamFilter):
    LOLS_API_URL = "https://api.lols.bot/account?id={id}"

    def is_spam(self, update: Update) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        message_author_id = update.message.from_user.id
        request_url = self.LOLS_API_URL.format(id=message_author_id)
        self.logger.info("[LOLS] Checking if user %d is banned..", message_author_id)
        account_status = self.try_send_request(request_url, [200])
        if not account_status:
            return False
        self.logger.info("[LOLS] User %d is%s banned", message_author_id, " not" if not account_status['banned'] else "")
        return account_status['banned']

    def get_priority(self) -> int:
        """Returns the priority of this filter. Higher == run's first"""
        return 1000