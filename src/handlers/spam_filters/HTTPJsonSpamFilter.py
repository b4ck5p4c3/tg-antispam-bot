from typing import Dict, Any, List

import requests

from src.handlers.spam_filters.SpamFilter import SpamFilter


class HTTPJsonSpamFilter(SpamFilter):
    _TIMEOUT_SEC = 5

    def try_send_request(self, url: str, acceptable_codes: List[int]) -> Dict[str, Any]:
        try:
            self.logger.debug("Sending request to %s", url)
            response = requests.get(url, timeout=self._TIMEOUT_SEC)
        except requests.exceptions.RequestException as e:
            self.logger.error("Request to %s failed: %s", url, e)
            return {}
        self.logger.debug("Request to %s finished with status code %d and body: %s", url, response.status_code, response.text)
        if response.status_code not in acceptable_codes:
            self.logger.error("Request to %s failed with status code %d. Body: %s", url, response.status_code, response.text)
            return {}
        try:
            return response.json()
        except ValueError:
            self.logger.error("Failed to parse JSON response from %s: %s", url, response.text)
            return {}
