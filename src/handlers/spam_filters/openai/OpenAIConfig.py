from openai.types import ChatModel
from pydantic import BaseModel


default_prompt = """
Please analyze the message provided below for signs of spam or fraud. Pay attention to the following aspects:

- Offers of high income in a short time or without effort.
- Invitations to contact via private messages or external links.
- Use of nonsensical symbols, emojis, or repetitive phrases.
- Advertising of dubious services or goods.
- Presence of links to external sites, bots, or suspicious resources.
- Promises of unrealistically favorable conditions.
- Casino ads
- ANY job offer
- Crypto buying and selling offers
- Messages that disguise promotion as "personal notes/materials" and invite users to contact privately
  (for example: trading "step-by-step guide", "human language", "if interested, contact me").

Note that messages are sent in a technical community chat, so discussions of hacks, exploits, and other specialized terms are absolutely normal.
Also, keep in mind that most messages will be in Russian, and this is not a sign of spam. Also in the end of the message i'll provide a attachments transcription, please use it for spam analysis.
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
    sussy_message_min_spamness: int = 35
    sussy_message_reaction: str = "👀"
