from pydantic import BaseModel


class Locale(BaseModel):
    openai_user_ban_notification: str
    chat_added_to_moderate: str
    chat_removed_from_moderate: str
    chat_not_moderated: str
    chat_already_moderated: str
    user_not_admin: str
    audit_log_chat_set: str
    audit_log_chat_updated: str
    audit_log_chat_removed: str
    audit_log_chat_not_set: str
    audit_log_chat_not_found: str
    ban_failed: str
    ban_success: str
    audit_log_user_banned_by_reply: str
    audit_log_user_banned_by_id: str
    ban_user_not_found: str
    durachok: str
