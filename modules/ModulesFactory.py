import logging
from typing import Dict, List

from modules.SpamFilter import SpamFilter
from modules.lols.LolsSpamFilter import LolsSpamFilter
from modules.openai.OpenAISpamFilter import OpenAISpamFilter


class ModulesFactory:

    @staticmethod
    def get_all(logger: logging.Logger) -> List[SpamFilter]:
        """Returns a list of all spam filters"""
        return [LolsSpamFilter(logger), OpenAISpamFilter(logger)]

    @staticmethod
    def get_all_mapped_by_priority(logger: logging.Logger) -> Dict[int, List[SpamFilter]]:
        """Returns a sorted dictionary of spam filters mapped by priority"""
        filters = ModulesFactory.get_all(logger)
        filters.sort(key=lambda x: x.get_priority())
        filters_map = {}
        for a_filter in filters:
            priority = a_filter.get_priority()
            if priority not in filters_map:
                filters_map[priority] = []
            filters_map[priority].append(a_filter)
        return filters_map
