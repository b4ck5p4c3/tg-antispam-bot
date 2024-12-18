from uvicorn import Config

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.handlers.spam_filters.lols.LolsSpamFilter import LolsSpamFilter
from src.handlers.spam_filters.openai.OpenAISpamFilter import OpenAISpamFilter, OpenAIFilterConfig


class FilterFactory:



    
    class Builder:
        def __init__(self, first_filter: SpamFilter):
            self.filters = [first_filter]

        def then(self, next_filter: SpamFilter) -> 'FilterFactory.Builder':
            self.filters.append(next_filter)
            return self

        def build(self) -> SpamFilter:
            for i in range(len(self.filters) - 1):
                self.filters[i].next_filter = self.filters[i + 1]
            return self.filters[0]

    @staticmethod
    def get_default_chain(config: Config, openai_config: OpenAIFilterConfig) -> SpamFilter:
        """Returns the default chain of spam spam_filters"""
        return FilterFactory.Builder(LolsSpamFilter(config)) \
            .then(OpenAISpamFilter(config, openai_config)) \
            .build()

