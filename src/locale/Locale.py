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
    coroner_usage: str = (
        "Coroner commands (administrators only):\n"
        "/coroner — global statistics and recent errors.\n"
        "/coroner help — show this help.\n"
        "/coroner ref <ID> — save a live reference; run inside a moderated group.\n"
        "/coroner start — verify the reference and start checks.\n"
        "/coroner stop — stop checks; observation continues.\n"
        "/coroner run G1|G2|G3|G4|ALL — queue checks; requires a running module.\n"
        "/coroner detectors — anomaly detector statistics and thresholds.\n"
        "/coroner quarantine — quarantined accounts and profile links.\n"
        "/coroner review — review deletion candidates.\n"
        "/coroner acknowledge — release a resolved protection incident.\n"
        "/coroner bypass — bypass removal percentage limits for the configured duration (2 hours by default).\n"
        "/coroner bypass stop — cancel the removal-limit bypass.\n"
        "Commands apply across all moderated chats. Subcommands and grades ignore case."
    )
    coroner_group_only: str = "Use Coroner in a private chat with the bot or a moderated group or supergroup."
    coroner_ref_group_only: str = "Set the reference with /coroner ref <ID> in a moderated group where the bot can look up this account."
    coroner_stopped: str = "Coroner is stopped. Observation continues; checks require /coroner start."
    coroner_error_stopped: str = "Coroner is in error. Correct the problem and use /coroner start; stop does not clear the safety lock."
    coroner_started: str = "Coroner started in all moderated chats."
    coroner_already_running: str = "Coroner is already running."
    coroner_not_running: str = "Checks are disabled. Use /coroner start first."
    coroner_ref_saved: str = "Reference account {user_id} saved with chat {chat_id}. Coroner remains stopped; use /coroner start."
    coroner_ref_required: str = "Set a live reference account with /coroner ref <ID> before starting."
    coroner_start_failed: str = "Coroner could not start. Use /coroner to view recent errors."
    coroner_ref_failed: str = "Could not save the reference account. Use /coroner to view recent errors."
    coroner_queued: str = "Added checks: {added}. Already queued: {existing}."
    coroner_update: str = "Update"
    coroner_heading: str = "Coroner — all moderated chats: {count}"
    coroner_status: str = "Status: {status}"
    coroner_dry_run: str = "Dry run: {value}"
    coroner_reference: str = "Reference: {user_id} (chat {chat_id}); every {every} checks"
    coroner_reference_missing: str = "Reference: not configured"
    coroner_reference_last: str = "Last reference check: {result}; {age} ago"
    coroner_reference_never: str = "Last reference check: not performed"
    coroner_reference_waiting: str = "Waiting for a successful reference check; deletions are blocked."
    coroner_monitored: str = "Monitored users (unique): {count}"
    coroner_untracked: str = "Untracked memberships: {value}"
    coroner_grade: str = "{grade}: {count}"
    coroner_queue: str = "Queued checks: {count}; longest current wait: {wait}"
    coroner_removed: str = "Removed users in the last 30 days (unique): {counts}"
    coroner_errors: str = "Errors (latest 5):"
    coroner_error_entry: str = "{age} ago · {text}{repeated}"
    coroner_error_chat: str = "Chat {chat_id}: {text}"
    coroner_repeated: str = " (repeated {count} times)"
    coroner_unknown: str = "unknown"
    coroner_alive: str = "alive"
    coroner_deleted: str = "deleted"
    coroner_yes: str = "yes"
    coroner_no: str = "no"
    coroner_unavailable: str = "unavailable"
    coroner_storage_error: str = "Cannot read or save Coroner JSON files. Checks are stopped; repair the files or permissions and restart the bot."
    coroner_config_error: str = "Invalid Coroner configuration. Check coroner_config.json and use /coroner start again."
    coroner_api_error: str = "Could not {operation}{subject}: {reason}. {action}"
    coroner_api_subject: str = " for user {user_id}"
    coroner_api_forbidden: str = "the bot does not have access or the required permissions"
    coroner_api_retry: str = "Telegram requested a pause"
    coroner_api_network: str = "Telegram is temporarily unavailable"
    coroner_api_bad_request: str = "Telegram rejected the request; check the chat, account and bot permissions"
    coroner_api_other: str = "an unexpected error occurred"
    coroner_retry_action: str = "The check will be retried."
    coroner_ui_action: str = "Try updating the status again later."
    coroner_operation_get_chat_member: str = "check the account and membership"
    coroner_operation_get_chat: str = "confirm the profile"
    coroner_operation_get_chat_member_count: str = "get the member count"
    coroner_operation_get_chat_administrators: str = "verify administrator access"
    coroner_operation_ban_chat_member: str = "permanently ban the account"
    coroner_operation_send_message: str = "send the status"
    coroner_operation_edit_message_text: str = "update the status"
    coroner_operation_answer_callback_query: str = "acknowledge the button"
    coroner_operation_default: str = "complete the operation"
    coroner_profile_unknown: str = "The profile for user {user_id} is incomplete or contradictory. No removal was performed; the check will be retried."
    coroner_invalid_participant: str = "User {user_id} was excluded from Coroner monitoring: Telegram rejected the participant ID. Further checks for this user are disabled."
    coroner_reference_failed: str = "CRITICAL: the reference account {user_id} was detected as deleted. Coroner is in error and requires a successful manual /coroner start."
    coroner_reference_unknown: str = "The reference account could not be verified as alive. Deletions are blocked until a successful reference check."
    coroner_protected_member: str = "Cannot remove user {user_id}: the account is a chat administrator or owner. No role changes were made."
    coroner_uncertain_removal: str = "The result of an interrupted removal of user {user_id} could not be confirmed. It was not counted as a successful removal."
    coroner_count_mismatch: str = "The saved participants and Telegram member count disagree. The untracked percentage is unavailable until membership is reconciled."
    coroner_worker_error: str = "Coroner encountered an internal error. The affected check will be retried; other bot functions remain available."
    coroner_safety_blocked: str = "Automatic removals are blocked. Administrator review is required. {reason}"
    coroner_safety_reason: str = "{kind}: {value} / {threshold}; scope: {scope}"
    coroner_safety_kind_false: str = "Deleted-profile ratio"
    coroner_safety_kind_candidates: str = "New daily deletion candidates"
    coroner_safety_kind_transitions: str = "Recently alive accounts returning deleted"
    coroner_safety_kind_profiles: str = "Incomplete or contradictory profiles"
    coroner_safety_kind_activity: str = "A quarantined account sent a new message"
    coroner_safety_kind_quota: str = "Removal budget exhausted"
    coroner_safety_kind_population: str = "Member counts cannot be verified"
    coroner_safety_kind_interrupted: str = "A removal has an uncertain result"
    coroner_safety_kind_budget_history: str = "Insufficient retained history for the configured removal window"
    coroner_safety_kind_manual: str = "An administrator requested manual review"
    coroner_protection_status: str = "Protection: {status}"
    coroner_protection_blocked: str = "blocked; manual review required"
    coroner_protection_clear: str = "active"
    coroner_quarantine_count: str = "Quarantined users: {count}"
    coroner_detectors: str = "Detectors"
    coroner_quarantine_button: str = "Quarantine"
    coroner_reviews: str = "Review removals"
    coroner_back: str = "Back"
    coroner_previous: str = "Previous"
    coroner_next: str = "Next"
    coroner_page: str = "Page {page}/{pages}"
    coroner_detector_heading: str = "Coroner — anomaly detectors"
    coroner_detector_title: str = "{kind}; scope {scope}; window {period}"
    coroner_detector_enabled: str = "Check enabled"
    coroner_detector_disabled: str = "Check disabled: insufficient data ({available})"
    coroner_detector_current: str = "Samples: {samples}; matches: {matches}; value: {value}{unit}; threshold: {threshold}{unit}; {progress}% of trigger threshold"
    coroner_detector_minimum: str = "Minimum sample: {samples}; minimum matching accounts/requests: {matches}"
    coroner_detector_candidates: str = "Currently quarantined: {count}; daily multiplier: {coefficient}; previous complete days, min / max / mean: {history}"
    coroner_detector_history: str = "Observed samples in {days} calendar days including today, min / max / mean:\nSamples: {samples}\nMatches: {matches}\nPercentage: {values}"
    coroner_detector_weighted: str = "Weighted historical percentage: {value}"
    coroner_count_history: str = "Historical count, min / max / mean: {history}"
    coroner_detector_checks: str = "Logical checks: {count}; is_alive == false: {deleted}; unknown: {unknown}. Trigger samples deduplicate users.\nHistorical checks, min / max / mean: {checks_history}\nHistorical false checks: {deleted_history}"
    coroner_quarantine_summary: str = "Quarantine: {count}; ready: {ready}; oldest: {oldest}\nRequired delay: {delay}\nHistorical size, min / max / mean: {history}\nCancelled candidates confirmed alive: {cancelled}"
    coroner_activity_settings: str = "Messages contradicting deletion: {count}; trigger: {minimum} users in {period}\nRecently alive means within {recent}\nConfirmed-alive cooldown: {cooldown}\nMetric sampling: {sampling}; calendar timezone: {timezone}; required daily coverage: {coverage}%"
    coroner_limit_summary: str = "Budget {name}: {period}\nGlobal usage: {count} removals; maximum fraction: {percent}%\nPer chat: at most {local_percent}%\nCurrent chat usage: {chats}\nPending and uncertain requests consume budget. An administrator can temporarily bypass percentage limits."
    coroner_limit_bypass_enabled: str = "Removal percentage limits bypassed. Other safeguards still apply."
    coroner_limit_bypass_disabled: str = "Removal percentage limits are enforced again."
    coroner_limit_bypass_already_active: str = "Removal-limit bypass is already active; its deadline was not extended."
    coroner_limit_bypass_failed: str = "Could not save the removal-limit bypass. Check Coroner errors."
    coroner_limit_bypass_off: str = "Removal-limit bypass: off"
    coroner_limit_bypass_active: str = "Removal-limit bypass: {remaining} remaining; administrator {user_id}"
    coroner_limit_bypass_button: str = "Bypass removal limits ({duration})"
    coroner_limit_bypass_cancel: str = "Cancel limit bypass"
    coroner_quota_reason: str = "{kind}: {value}% / {threshold}%; scope: {scope}"
    coroner_removed_period: str = "Removals in the last {days} days; percentages use current summed chat memberships:"
    coroner_removed_grade: str = "{grade}: {users} unique users, {count} chat removals ({percent})"
    coroner_review_heading: str = "Coroner — deletion review"
    coroner_review_counts: str = "Current quarantine: {users} users, {targets} chat removals."
    coroner_review_chat_distribution: str = "Quarantined accounts per chat:"
    coroner_review_stale: str = "This action is no longer supported. Showing the current quarantine."
    coroner_review_decided: str = "Current anomalies approved until their parameters normalize. New accounts are covered; quarantine and other safeguards still apply."
    coroner_review_allowed_reason: str = "Approved: {reason}"
    coroner_review_failed: str = "Could not save anomaly approval. Check Coroner errors."
    coroner_review_no_anomalies: str = "No new anomalies to approve. Quarantine, reference checks and removal limits still apply."
    coroner_review_permissions: str = "Approved anomalies: {count}; each permission resets when its parameter normalizes."
    coroner_stop_module: str = "Stop Coroner"
    coroner_profile_buttons_unavailable: str = "Telegram blocks account-link buttons for these IDs in this chat. Other account buttons remain available:"
    coroner_account_links_loading: str = "Checking account links… You can still use Stop and navigation."
    coroner_account_links_failed: str = "Could not finish checking account links. Press Update to retry."
    coroner_review_cannot_resume: str = "Cannot release the safety block: quarantine is not empty or a detector is still triggered. Review candidates and resolve the cause first."
    coroner_review_resumed: str = "Safety incident acknowledged. Removal budgets were preserved; normal checks and quarantine still apply."
    coroner_approve_all: str = "Confirm all accounts"
    coroner_no_candidates: str = "No accounts in this list."
