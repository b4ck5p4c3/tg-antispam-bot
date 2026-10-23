CORONER_MESSAGES = {
    "usage": ("Coroner commands (administrators only):\n"
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
              "Commands apply across all moderated chats. Subcommands and grades ignore case."),
    "group_only": "Use Coroner in a private chat with the bot or a moderated group or supergroup.",
    "ref_group_only": "Set the reference with /coroner ref <ID> in a moderated group where the bot can look up this account.",
    "stopped": "Coroner is stopped. Observation continues; checks require /coroner start.",
    "error_stopped": ("Coroner is in error. Correct the problem and use /coroner start; "
                      "stop does not clear the safety lock."),
    "started": "Coroner started in all moderated chats.",
    "already_running": "Coroner is already running.",
    "not_running": "Checks are disabled. Use /coroner start first.",
    "ref_saved": "Reference account {user_id} saved with chat {chat_id}. Coroner remains stopped; use /coroner start.",
    "ref_required": "Set a live reference account with /coroner ref <ID> before starting.",
    "start_failed": "Coroner could not start. Use /coroner to view recent errors.",
    "ref_failed": "Could not save the reference account. Use /coroner to view recent errors.",
    "queued": "Added checks: {added}. Already queued: {existing}.",
    "update": "Update",
    "heading": "Coroner — all moderated chats: {count}",
    "status": "Status: {status}",
    "dry_run": "Dry run: {value}",
    "reference": "Reference: {user_id} (chat {chat_id}); every {every} checks",
    "reference_missing": "Reference: not configured",
    "reference_last": "Last reference check: {result}; {age} ago",
    "reference_never": "Last reference check: not performed",
    "reference_waiting": "Waiting for a successful reference check; deletions are blocked.",
    "monitored": "Monitored users (unique): {count}",
    "untracked": "Untracked memberships: {value}",
    "untracked_chat": "{chat} - {value}",
    "unknown_chat": "Unknown chat",
    "grade": "{grade}: {count}",
    "queue": "Queued checks: {count}; longest current wait: {wait}",
    "removed": "Removed users in the last 30 days (unique): {counts}",
    "errors": "Errors (latest 5):",
    "error_entry": "{age} ago · {text}{repeated}",
    "error_chat": "Chat {chat_id}: {text}",
    "repeated": " (repeated {count} times)",
    "unknown": "unknown",
    "alive": "alive",
    "deleted": "deleted",
    "yes": "yes",
    "no": "no",
    "unavailable": "unavailable",
    "storage_error": ("Cannot read or save the Coroner SQLite database. Checks are stopped; "
                      "repair the database or permissions and restart the bot."),
    "config_error": "Invalid Coroner configuration. Check coroner_config.json and use /coroner start again.",
    "api_error": "Could not {operation}{subject}: {reason}. {action}",
    "api_subject": " for user {user_id}",
    "api_forbidden": "the bot does not have access or the required permissions",
    "api_retry": "Telegram requested a pause",
    "api_network": "Telegram is temporarily unavailable",
    "api_invalid_response": "Telegram or its API proxy returned an invalid response (not valid JSON); the service may be temporarily unavailable",
    "api_bad_request": "Telegram rejected the request; check the chat, account and bot permissions",
    "api_other": "an unexpected error occurred",
    "retry_action": "The check will be retried.",
    "ui_action": "Try updating the status again later.",
    "operation_get_chat_member": "check the account and membership",
    "operation_get_chat": "confirm the profile",
    "operation_get_chat_member_count": "get the member count",
    "operation_get_chat_administrators": "verify administrator access",
    "operation_ban_chat_member": "permanently ban the account",
    "operation_send_message": "send the status",
    "operation_edit_message_text": "update the status",
    "operation_answer_callback_query": "acknowledge the button",
    "operation_default": "complete the operation",
    "profile_unknown": ("The profile for user {user_id} is incomplete or contradictory. "
                        "No removal was performed; the check will be retried."),
    "reference_failed": ("CRITICAL: the reference account {user_id} was detected as deleted. "
                         "Coroner is in error and requires a successful manual /coroner start."),
    "reference_unknown": ("The reference account could not be verified as alive. "
                          "Deletions are blocked until a successful reference check."),
    "protected_member": ("Cannot remove user {user_id}: the account is a chat administrator "
                         "or owner. No role changes were made."),
    "uncertain_removal": ("The result of an interrupted removal of user {user_id} could not "
                          "be confirmed. It was not counted as a successful removal."),
    "count_mismatch": ("The saved participants and Telegram member count disagree. "
                       "The untracked percentage is unavailable until membership is reconciled."),
    "worker_error": ("Coroner encountered an internal error. The affected check will be retried; "
                     "other bot functions remain available."),
    "safety_blocked": "Automatic removals are blocked. Administrator review is required. {reason}",
    "safety_reason": "{kind}: {value} / {threshold}; scope: {scope}",
    "safety_kind_false": "Deleted-profile ratio",
    "safety_kind_candidates": "New daily deletion candidates",
    "safety_kind_transitions": "Recently alive accounts returning deleted",
    "safety_kind_profiles": "Incomplete or contradictory profiles",
    "safety_kind_activity": "A quarantined account sent a new message",
    "safety_kind_quota": "Removal budget exhausted",
    "safety_kind_population": "Member counts cannot be verified",
    "safety_kind_interrupted": "A removal has an uncertain result",
    "safety_kind_budget_history": "Insufficient retained history for the configured removal window",
    "safety_kind_manual": "An administrator requested manual review",
    "protection_status": "Protection: {status}",
    "protection_blocked": "blocked; manual review required",
    "protection_clear": "active",
    "quarantine_count": "Quarantined users: {count}",
    "detectors": "Detectors",
    "quarantine_button": "Quarantine",
    "reviews": "Review removals",
    "back": "Back",
    "previous": "Previous",
    "next": "Next",
    "page": "Page {page}/{pages}",
    "detector_heading": "Coroner — anomaly detectors",
    "detector_title": "{kind}; scope {scope}; window {period}",
    "detector_enabled": "Check enabled",
    "detector_disabled": "Check disabled: insufficient data ({available})",
    "detector_current": "Samples: {samples}; matches: {matches}; value: {value}{unit}; threshold: {threshold}{unit}; {progress}% of trigger threshold",
    "detector_minimum": "Minimum sample: {samples}; minimum matching accounts/requests: {matches}",
    "detector_candidates": "Currently quarantined: {count}; daily multiplier: {coefficient}; previous complete days, min / max / mean: {history}",
    "detector_history": "Observed samples in {days} calendar days including today, min / max / mean:\nSamples: {samples}\nMatches: {matches}\nPercentage: {values}",
    "detector_weighted": "Weighted historical percentage: {value}",
    "count_history": "Historical count, min / max / mean: {history}",
    "detector_checks": "Logical checks: {count}; is_alive == false: {deleted}; unknown: {unknown}. Trigger samples deduplicate users.\nHistorical checks, min / max / mean: {checks_history}\nHistorical false checks: {deleted_history}",
    "quarantine_summary": "Quarantine: {count}; ready: {ready}; oldest: {oldest}\nRequired delay: {delay}\nHistorical size, min / max / mean: {history}\nCancelled candidates confirmed alive: {cancelled}",
    "activity_settings": "Messages contradicting deletion: {count}; trigger: {minimum} users in {period}\nRecently alive means within {recent}\nConfirmed-alive cooldown: {cooldown}\nMetric sampling: {sampling}; calendar timezone: {timezone}; required daily coverage: {coverage}%",
    "limit_summary": "Budget {name}: {period}\nGlobal usage: {count} removals; maximum fraction: {percent}%\nPer chat: at most {local_percent}%\nCurrent chat usage: {chats}\nPending and uncertain requests consume budget. An administrator can temporarily bypass percentage limits.",
    "limit_bypass_enabled": "Removal percentage limits bypassed. Other safeguards still apply.",
    "limit_bypass_disabled": "Removal percentage limits are enforced again.",
    "limit_bypass_already_active": "Removal-limit bypass is already active; its deadline was not extended.",
    "limit_bypass_failed": "Could not save the removal-limit bypass. Check Coroner errors.",
    "limit_bypass_off": "Removal-limit bypass: off",
    "limit_bypass_active": "Removal-limit bypass: {remaining} remaining; administrator {user_id}",
    "limit_bypass_button": "Bypass removal limits ({duration})",
    "limit_bypass_cancel": "Cancel limit bypass",
    "quota_reason": "{kind}: {value}% / {threshold}%; scope: {scope}",
    "removed_period": "Removals in the last {days} days; percentages use current summed chat memberships:",
    "removed_grade": "{grade}: {users} unique users, {count} chat removals ({percent})",
    "review_heading": "Coroner — deletion review",
    "review_counts": "Current quarantine: {users} users, {targets} chat removals.",
    "review_chat_distribution": "Quarantined accounts per chat:",
    "review_stale": "This action is no longer supported. Showing the current quarantine.",
    "review_decided": "Current anomalies approved until their parameters normalize. New accounts are covered; quarantine and other safeguards still apply.",
    "review_allowed_reason": "Approved: {reason}",
    "review_failed": "Could not save anomaly approval. Check Coroner errors.",
    "review_no_anomalies": "No new anomalies to approve. Quarantine, reference checks and removal limits still apply.",
    "review_permissions": "Approved anomalies: {count}; each permission resets when its parameter normalizes.",
    "stop_module": "Stop Coroner",
    "profile_buttons_unavailable": "Telegram blocks account-link buttons for these IDs in this chat. Other account buttons remain available:",
    "account_links_loading": "Checking account links… You can still use Stop and navigation.",
    "account_links_failed": "Could not finish checking account links. Press Update to retry.",
    "review_cannot_resume": "Cannot release the safety block: quarantine is not empty or a detector is still triggered. Review candidates and resolve the cause first.",
    "review_resumed": "Safety incident acknowledged. Removal budgets were preserved; normal checks and quarantine still apply.",
    "approve_all": "Confirm all accounts",
    "no_candidates": "No accounts in this list.",
}


def coroner_text(locale, key: str, **values) -> str:
    return getattr(locale, f"coroner_{key}", CORONER_MESSAGES[key]).format(**values)


def shorten(text: str, limit: int) -> str:
    """Bound UTF-16 length too, so supplementary characters cannot overflow Telegram."""
    encoded = text.encode("utf-16-le", errors="replace")
    if len(encoded) <= limit * 2:
        return text
    return encoded[:(limit - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}min {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}min"
