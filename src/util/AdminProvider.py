import os
import time
from logging import Logger

import requests


class AdminProvider:
    """Provides a list of admin users"""

    CACHE_LIFETIME_SEC = 60
    __CACHE_UPDATED_AT = 0
    SWYNCA_API_URL="https://re-swynca.app.0x08.in/"



    def __init__(self, logger: Logger, token=None):
        self.admins = None
        self.logger = logger
        if token is None:
            swynca_api_key = os.getenv("SWYNCA_API_KEY")
        else:
            swynca_api_key = token
        self.session = requests.Session()
        self.session.headers.update({'Cookie': f"session={swynca_api_key}",
                                     "accept":"application/json",
                                     "User-Agent":"Tg-antispam"}
                                    )

    def is_admin(self, user_id: int) -> bool:
        if self.__required_cache_update():
            self.admins = self.__request_admins()
            return user_id in self.admins
        else:
            return user_id in self.admins

    def __request_admins(self) -> list[int]:
        response = self.session.get(self.SWYNCA_API_URL+"api/members")
        if response.status_code!=200:
            self.logger.error("Swynca returned %d status code, body: %s", response.status_code, response.text)
        else:
            admins = response.json()
            self.admins = [int(admin['telegramMetadata']['telegramId']) for admin in admins]
            self.logger.debug("Admins: %s", self.admins)
            return self.admins

    def __required_cache_update(self) -> bool:
        if self.admins is None:
            self.logger.debug("Cache is empty, updating")
            return True
        elif self._cache_outdated():
            self.logger.debug("Cache is outdated, updating")
            return True
    def _cache_outdated(self):
        self.__CACHE_UPDATED_AT = time.time()
        self.logger.debug("Cache updated at %d", self.__CACHE_UPDATED_AT)
        return False
