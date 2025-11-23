import time
from threading import Timer
from typing import Dict
from venv import logger

from telegram import Update
from telegram.ext import CallbackContext

from src.handlers.spam_filters.HTTPJsonSpamFilter import HTTPJsonSpamFilter
from src.util.config.Config import Config


class LolsSpamFilter(HTTPJsonSpamFilter):
    __LOLS_API_BASE_URL = "https://api.lols.bot"
    __LOLS_CHECK_API = f"{__LOLS_API_BASE_URL}/account?id="
    __LOLS_GET_BANNED_IDS_API = f"{__LOLS_API_BASE_URL}/lists"

    __CACHE_UPDATE_INTERVAL_SEC = 60*60
    __CACHE_MAX_AGE_SEC = 60*60*72
    __CACHE_LIST_NAME = "spammers-1h"
    __CACHE_LIST_REQUESTS_BY_TIMESTAMP: Dict[float, set[int]] = {}

    _filter_name = "Lols"

    def __init__(self, config: Config):
        super().__init__(config)
        self.__schedule_cache_update()


    async def _is_spam(self, update: Update, context: CallbackContext) -> bool:
        """Checks if message is spam. Returns true if message is spam"""
        message_author_id = update.message.from_user.id
        return self.is_spam(message_author_id)

    def is_spam(self, user_id: int) -> bool:
        if self.__is_in_cache(user_id):
            logger.info(f"User {user_id} is in cache")
            return True
        request_url = self.__LOLS_CHECK_API+str(user_id)
        account_status = self.try_send_request(request_url, [200])
        if not account_status:
            return False
        self.logger.info(f"User {user_id}: {account_status}")
        return account_status['banned']

    def __schedule_cache_update(self):
        self.__invalidate_outdated_cache()
        self.__update_cache()
        timer: Timer = Timer(self.__CACHE_UPDATE_INTERVAL_SEC, self.__schedule_cache_update)
        timer.daemon = True
        timer.start()


    def __is_in_cache(self, user_id: int) -> bool:
        for banned_ids_list in self.__CACHE_LIST_REQUESTS_BY_TIMESTAMP.values():
            if user_id in banned_ids_list:
                return True
        return False


    def __update_cache(self):
        self.logger.info(f"Updating cache for {self.__CACHE_LIST_NAME}")
        lists_mappings = self.try_send_request(self.__LOLS_GET_BANNED_IDS_API, [200])
        lists_mapping = None
        for lists_mapping_candidate in lists_mappings:
            if lists_mapping_candidate['id'] == self.__CACHE_LIST_NAME:
                lists_mapping = lists_mapping_candidate
                break
        if lists_mapping is None:
            self.logger.error(f"List {self.__CACHE_LIST_NAME} not found in {lists_mappings}. Passing")
            return
        list_url = lists_mapping['format']['json']
        banned_ids = self.try_send_request(list_url, [200])
        banned_ids = set([int(user_id) for user_id in banned_ids])
        updated_at = time.time()
        self.__CACHE_LIST_REQUESTS_BY_TIMESTAMP[updated_at] = banned_ids
        logger.info(f"Cache updated at {updated_at} with {len(banned_ids)} banned ids")

    def __invalidate_outdated_cache(self):
        current_time = time.time()
        for timestamp in list(self.__CACHE_LIST_REQUESTS_BY_TIMESTAMP.keys()):
            if current_time - timestamp > self.__CACHE_MAX_AGE_SEC:
                self.logger.debug(f"Invalidating cache for {self.__CACHE_LIST_NAME} at {timestamp}")
                del self.__CACHE_LIST_REQUESTS_BY_TIMESTAMP[timestamp]
