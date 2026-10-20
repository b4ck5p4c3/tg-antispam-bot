from typing import Literal

from pydantic import BaseModel, Field

from src.util.data.BotState import MessageRevision


class OpenAIMessageInput(BaseModel):
    target_message: str
    attachment_transcript: str
    replied_to_message: str
    message_history: list[MessageRevision] = Field(default_factory=list)


class SpamClassification(BaseModel):
    verdict: Literal["spam", "not_spam"]
    reason: str


SPAM_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["spam", "not_spam"],
        },
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}
