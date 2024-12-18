import os
import re

import httpx
from openai import OpenAI
from openai.types import ChatModel
from pydantic import BaseModel
from telegram import ChatPermissions
from telegram.ext import CallbackContext

from src.handlers.spam_filters.SpamFilter import SpamFilter, extract_message_text
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.config.Config import Config

default_prompt = """
Please analyze the message provided below for signs of spam or fraud. Pay attention to the following aspects:

- Offers of high income in a short time or without effort.
- Invitations to contact via private messages or external links.
- Use of nonsensical symbols, emojis, or repetitive phrases.
- Advertising of dubious services or goods.
- Presence of links to external sites, bots, or suspicious resources.
- Promises of unrealistically favorable conditions.

Note that messages are sent in a technical community chat, so discussions of hacks, exploits, and other specialized terms are absolutely normal. 
Also, keep in mind that most messages will be in Russian, and this is not a sign of spam. 
After analysis, provide a brief justification of your conclusions and evaluate the "spamness" of the message as a percentage from 0% to 100%, where 0% is absolutely not spam, and 100% is clear spam. 
If the message is too short or lacks logical content, report this and set the spamness to 0%.

Format your response as follows (STRICTLY IN THIS FORMAT, DEVIATION IS PROHIBITED): [Your justification] (spamness [percentage]%)
"""

class OpenAIPromptConfig(BaseModel):
    temperature: float = 1.0
    max_tokens: int = 512
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

class OpenAIFilterConfig(BaseModel):
    prompt: str = default_prompt
    prompt_config: OpenAIPromptConfig = OpenAIPromptConfig()
    model: ChatModel = "gpt-4o-mini"
    min_spamness_percent: int = 65
    ban_delay_sec: int = 60 * 10
    ban_notification_message_delete_delay_sec: int = 30
    sussy_message_min_spamness: int = 45
    sussy_message_reaction: str = "👀"

class OpenAISpamFilter(SpamFilter):
    _NOT_FOUND = -1
    __MESSAGE_SPAMNESS_MAP = {}
    _filter_name = "OpenAI"

    def __init__(self, config: Config, openai_config: OpenAIFilterConfig):
        super().__init__(config)
        token = os.environ.get("OPENAI_API_KEY")
        proxy_url = os.environ.get("OPENAI_PROXY_URL")
        if not token:
            self.logger.warning("OPENAI_TOKEN token is not set. Module is disabled")
            self.openai_client = None
        else:
            self.openai_client = OpenAI() if proxy_url is None or proxy_url == "" else OpenAI(
                http_client=httpx.Client(proxy=proxy_url))
        self.openai_config = openai_config

    def _find_spamness_percent(self, text: str) -> int:
        percent_search = list(re.finditer(r"(\d+)%", text))
        if percent_search:
            spamness_percent = percent_search[-1].group(1)
            try:
                spamness_percent = int(spamness_percent)
            except ValueError:
                self.logger.error(f"Failed to parse spamness percent from OpenAI response: {text}")
                return self._NOT_FOUND
            return spamness_percent
        else:
            self.logger.error(f"Failed to parse spamness percent from OpenAI response: {text}")
            return self._NOT_FOUND

    def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        if not self.openai_client:
            return False
        """Checks if message is spam. Returns true if message is spam"""
        response = self._openai_check_message(extract_message_text(update))
        answer_text = response.choices[0].message.content
        spamness_percent = self._find_spamness_percent(answer_text)
        if spamness_percent == self._NOT_FOUND:
            return False
        self.logger.info(f"Spamness of message {update.message.id}: {spamness_percent}%")
        self.__MESSAGE_SPAMNESS_MAP[update.message.id] = spamness_percent
        return spamness_percent >= self.openai_config.min_spamness_percent

    async def _on_spam(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        """Handles the action to take when a message is identified as spam."""
        user = update.message.from_user
        chat_id = update.message.chat_id
        await self.telegram_helper.try_remove_message(context, update.message)
        await self.telegram_helper.restrict_chat_member(context, chat_id, user.id, ChatPermissions(can_send_messages=False))
        ban_message = await self.telegram_helper.send_message(context, chat_id, self._get_restrict_message(update))
    
        await self.telegram_helper.delete_message_with_delay(context, ban_message, self.openai_config.ban_notification_message_delete_delay_sec)
        context.job_queue.run_once(lambda ctx: self.telegram_helper.ban_message_author(context, update.message), self.openai_config.ban_delay_sec)

    async def _on_pass(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        await super()._on_pass(update, context)
        if update.message.id in self.__MESSAGE_SPAMNESS_MAP:
            if self.__MESSAGE_SPAMNESS_MAP[update.message.id] >= self.openai_config.sussy_message_min_spamness:
                await self.telegram_helper.add_message_reaction(context, update.message, self.openai_config.sussy_message_reaction)
            del self.__MESSAGE_SPAMNESS_MAP[update.message.id]


    def _get_restrict_message(self, update: EnrichedUpdate) -> str:
        return update.locale.openai_user_ban_notification.format(
            user=update.message.from_user,
            spamness=self.__MESSAGE_SPAMNESS_MAP[update.message.id],
            ban_delay_min=self.openai_config.ban_delay_sec // 60
        )


    def _openai_check_message(self, message: str):
        response = self.openai_client.chat.completions.create(
            model=self.openai_config.model,
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": self.openai_config.prompt
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": message
                        }
                    ]
                }
            ],
            temperature=self.openai_config.prompt_config.temperature,
            max_tokens=self.openai_config.prompt_config.max_tokens,
            top_p=self.openai_config.prompt_config.top_p,
            frequency_penalty=self.openai_config.prompt_config.frequency_penalty,
            presence_penalty=self.openai_config.prompt_config.presence_penalty,
            response_format={
                "type": "text"
            }
        )
        return response
