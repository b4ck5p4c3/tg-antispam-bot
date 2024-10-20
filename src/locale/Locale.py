from pydantic import BaseModel


class Locale(BaseModel):
    openai_user_ban_notification: str
    chat_added_to_moderate: str
    chat_removed_from_moderate: str
    chat_not_moderated: str
    chat_already_moderated: str
    user_not_admin: str