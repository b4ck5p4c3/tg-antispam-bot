from telegram import Update

from modules.HTTPJsonSpamFilter import HTTPJsonSpamFilter


class CASSpamFilter(HTTPJsonSpamFilter):
    CAS_API_URL = "https://api.cas.chat/check?user_id={id}"

    def is_spam(self, update: Update) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        message_author_id = update.message.from_user.id
        request_url = self.CAS_API_URL.format(id=message_author_id)
        account_status = self.try_send_request(request_url, [200])
        if not account_status:
            return False
        return not account_status['ok']

    def get_priority(self) -> int:
        """Returns the priority of this filter. Higher == run's first"""
        return 1000