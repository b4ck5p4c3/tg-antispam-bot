from pydantic import BaseModel


class Locale(BaseModel):
    openai_user_ban_notification: str
    chat_added_to_moderate: str
    chat_removed_from_moderate: str
    chat_not_moderated: str
    chat_already_moderated: str
    audit_log_chat_set: str
    audit_log_chat_updated: str
    audit_log_chat_removed: str
    audit_log_chat_not_found: str
    ban_failed: str
    ban_success: str
    ban_username_not_found: str = "This username is not in the bot's saved user cache. Use the numeric user ID or reply to the user's message."
    ban_username_changed: str = "The username has changed. Use the numeric user ID or reply to the user's message."
    unban_usage: str = "Reply to a registered ban audit message with /unban, or use /unban <user ID|@username>."
    unban_audit_log_not_found: str = "This message is not registered as a user ban audit entry. Use /unban <user ID|@username>."
    unban_username_not_found: str = "This username is not in the bot's saved user cache. Use the numeric user ID or reply to a registered ban audit message."
    unban_username_changed: str = "The username has changed. Run /unban again using the numeric user ID."
    unban_permission_denied: str = "You must be an administrator of the target chat to unban a user there."
    unban_request_not_found: str = "This unban request is unavailable. Send /unban again."
    unban_already_processed: str = "This chat has already been processed."
    unban_result_header: str = "Unban user {user_id}"
    unban_not_banned: str = "The user is not banned in any moderated chat."
    unban_choose_chats: str = "The user is still banned in the chats below. Select a chat to unban them."
    unban_success: str = "Unbanned in {chat}."
    unban_chat_not_banned: str = "The user is no longer banned in {chat}."
    unban_pending: str = "Banned in {chat}."
    unban_failed: str = "Could not unban in {chat}: {error}"
    unban_scan_failed: str = "Could not check chat {chat_id}: {error}"
    unban_button: str = "Unban in {chat}"
    ban_channel_failed: str
    ban_channel_success: str
    audit_log_user_banned_by_reply: str
    audit_log_channel_banned_by_reply: str
    audit_log_user_banned_by_id: str
    audit_log_user_banned_by_username: str = "User {banned_id} has been banned by [{banned_by.first_name}](tg://user?id={banned_by.id}) ({banned_by.id}) in chat **{chat.title}** using @{username}"
    ban_user_not_found: str
    durachok: str
    ban_community_not_found: str
    ban_community_success: str
    ban_community_failed: str
    community_already_banned: str
    audit_log_community_banned_by_id: str
    audit_log_community_not_found: str
    report_usage: str
    report_subscribed: str
    report_unsubscribed: str
    report_already_subscribed: str
    report_not_subscribed: str
    report_reply_required: str
    report_already_exists: str
    report_rate_limit_hour: str
    report_reporting_now: str
    report_reported: str
    report_ban_button: str
    report_ignore_button: str
    report_notification_message: str
    report_non_text_message_placeholder: str
    report_notification_message_user_banned: str
    report_notification_message_user_ignored: str
    report_list_empty: str
    report_list_subscribers: str
    service_usage: str
    service_subscribed: str
    service_unsubscribed: str
    service_already_subscribed: str
    service_not_subscribed: str
    service_list_empty: str
    service_list_subscribers: str
    openai_service_unavailable: str
    openai_service_recovered: str
