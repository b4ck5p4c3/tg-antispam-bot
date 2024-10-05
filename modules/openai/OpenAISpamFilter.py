import os
import re
from logging import Logger

import httpx
from openai import OpenAI
from telegram import Update, Message

from modules.SpamFilter import SpamFilter


class OpenAISpamFilter(SpamFilter):
    MIN_SPAMNESS_PERCENT = 65

    def __init__(self, a_logger: Logger):
        super().__init__(a_logger)
        token = os.getenv("OPENAI_API_KEY")
        proxy_url = os.environ.get("OPENAI_PROXY_URL")
        if not token:
            self.logger.warning("OPENAI_TOKEN token is not set. Module is disabled")
            self.openai_client = None
        else:
            self.openai_client = OpenAI() if proxy_url is None or proxy_url == "" else OpenAI(
                http_client=httpx.Client(proxy=proxy_url))
    def is_spam(self, update: Update) -> bool:
        if not self.openai_client:
            return False
        """Checks if message is spam. Returns true if message is spam"""
        response = self.openai_check_message(update.message.text)
        text_answer = response.choices[0].message.content
        percent_search = list(re.finditer(r"(\d+)%", text_answer))
        if percent_search:
            spamness_percent = percent_search[-1].group(1)
            try:
                spamness_percent = int(spamness_percent)
            except ValueError:
                self.logger.error("Failed to parse spamness percent from OpenAI response: %s", text_answer)
                return False
            if spamness_percent >= self.MIN_SPAMNESS_PERCENT:
                self.logger.info("OpenAI thinks that message is spam. Spamness: %d%%", spamness_percent)
                return True
            else:
                self.logger.info("OpenAI thinks that message is not spam. Spamness: %d%%", spamness_percent)
        else:
            self.logger.error("Failed to parse spamness percent from OpenAI response: %s", text_answer)
        return False

    def openai_check_message(self, message: str):
        response = self.openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": "Пожалуйста, проанализируй предоставленное ниже сообщение на наличие признаков спама или мошенничества. Обрати внимание на следующие аспекты:\n\n    Предложения о высоком доходе за короткий срок или без усилий.\n    Призывы связаться через личные сообщения или по внешним ссылкам.\n    Использование неосмысленных символов, эмодзи или повторяющихся фраз.\n    Реклама сомнительных услуг или товаров.\n    Наличие ссылок на внешние сайты, боты или подозрительные ресурсы.\n    Обещания нереалистично выгодных условий.\n\nУчтивай что сообщения отправляются в чате технического сообщества, следовательно абсолютно нормально обсуждение взломов, хаков, других узкоспециализированных терминов. После анализа предоставь краткое обоснование своих выводов и оцени \"спамность\" сообщения в процентах от 0% до 100%, где 0% — абсолютно не спам, а 100% — явный спам. Если сообщение слишком короткое или не содержит логической нагрузки сообщи об этом и установи спамность как 0%\n\nФорматируй ответ следующим образом (СТРОГО В ЭТОМ ФОРМАТЕ, ЗАПРЕЩЕНО ОТХОДИТЬ ОТ НЕГО): [Твое обоснование] (спамность [процент]%)"
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
            temperature=1,
            max_tokens=512,
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0,
            response_format={
                "type": "text"
            }
        )
        return response

    def get_priority(self) -> int:
        """Returns the priority of this filter. Higher == run's first"""
        return 10000

