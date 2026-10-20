# B4CKSP4CE Telegram Antispam Bot

## Description

The B4CKSP4CE Telegram Antispam Bot is designed to help manage and moderate Telegram chats by automatically detecting
and handling spam messages. It uses a combination of predefined filters and AI-based analysis to ensure that your chat
remains free from unwanted content.
Bot using webhooks to receive messages from Telegram and OpenAI API to analyze messages

## How It Moderates Messages

The bot uses a chain of spam filters to evaluate each incoming message. These filters can be simple rule-based checks or
more complex AI-driven analyses. If a message is identified as spam, the bot can take actions such as deleting the
message or banning the user

The first checked message from each user in each chat remains monitored after the user becomes trusted.
Every edit is checked again, with all recorded earlier versions (text/caption, OCR transcription, and reply context)
included in the AI request. The history and edit counter are persisted in `data/state.json` across restarts.
Admins, anonymous admins, linked-channel automatic forwards, and chats without moderation remain exempt.

Set `max_message_edits` in `data/openai_config.json` to change the edit limit (default: `10`; minimum: `0`).
Edits 1–10 are checked normally; edit 11 deletes the message and bans its author immediately, before OCR or any
external spam checks. Restart the bot after changing the configuration.
For users already trusted before history tracking was enabled, the first observed edit starts tracking that message.
Telegram does not provide versions from before the bot started recording them.

## How to run it without B4CKSP4CE infrastructure

1. Clone the repository and navigate to the project directory `cd tg_antispam_bot`
2. Build the Docker image using `docker build -t tg_antispam_bot .`
3. Run the bot using
   `docker run --env TELEGRAM_BOT_TOKEN=<BOT_TOKEN> -v data:/app/data tg_antispam_bot --polling --no-swynca`.
4. Enable moderation in the chat by sending `/moderate` command.
   Optionally, you can provide the `OPENAI_API_KEY` env variable for filtering messages using OpenAI API.

## Available commands

- `/moderate`: Add chat to the list of moderated chats
- `/abandon`: Remove chat from the list of moderated chats
- `/ban`: Ban a user from the chat by replying to their message or providing a user ID or `@username`
- `/unban`: Unban a user by replying to a registered ban audit message, or by providing a user ID or `@username`
- `/banc`: Restrict reposting of messages from the chat (only first message)
- `/report`: Report spam and manage report notification subscriptions
- `/as_service`: Manage service notification subscriptions
- `/set_audit_log`: Set chat for [audit logging](#audit-logging)
- `/unset_audit_log`: Unset chat for audit logging

## Audit logging

The bot will log all usage of the `/ban` command in the chat configured for audit logging.
By default, logs are saved in the chat where the command was executed. However, you can specify a different chat for
logging by using the `/set_audit_log` command.

`/ban @username` resolves usernames case-insensitively using the persistent user cache and checks the user's current
username before banning. For unknown or changed usernames, use a numeric ID or reply to the user's message instead.

New user ban audit messages are registered in `data/state.json`, keyed by the audit chat ID and message ID.
Each entry stores the banned user ID and the original chat ID; `/unban` never extracts IDs from audit message text.
Both text and photo audit messages are registered, including logs sent to the original chat when no audit chat is set.
Older audit messages without registry entries require `/unban <user ID>` or `/unban @username` instead.

Replying to a registered audit message with `/unban` immediately unbans the user in the original chat and checks
the other moderated chats for bans. Each remaining ban gets its own unban button.
With `/unban <user ID>` or `/unban @username`, a single confirmed ban is removed immediately;
multiple bans are presented as separate chat buttons. If some chats cannot be checked, the response reports those
errors and offers buttons for the confirmed bans instead of assuming there is only one.
Each successful button click removes that button and updates the same response with the chat where the user was
unbanned. Responses are kept permanently, and their button state also survives bot restarts.

Commands can be sent in a chat or privately by administrators of moderated chats. Unauthorized `/unban` commands
are silently ignored, including invalid arguments and unknown usernames. Replies to audit messages require
administrator access in the original chat; administrator access in the audit chat alone is insufficient.
Every unban, including button clicks, checks administrator access in the target chat. Unauthorized button clicks
are acknowledged without an alert or message change. Chats removed from moderation cannot be unbanned through
old buttons. `@username` lookup uses the persistent user cache, so unknown usernames require a numeric ID.
The user's current username is checked again before unbanning. Unbans use
[`only_if_banned`](https://core.telegram.org/bots/api#unbanchatmember), so active members are not kicked.

⚠ Topics are not supported in audit logs. If you want to use audit logging, make sure to disable topics in the chat.

## Run arguments

- `--polling`: Use polling instead of webhooks
- `--no-swynca`: Disable Swynca for admin list providing, use message chat admins instead
- `--development`: Enable development-only moderation behavior, including delayed automatic unban

## Coroner: deleted accounts

Coroner observes members of moderated groups, saves its roster and queue in JSON,
and checks accounts periodically. It starts **stopped** on the first launch. Later
restarts preserve its saved status: `running` resumes after a fresh reference check,
while `stopped` and `error` require a manual start. Observation continues while stopped;
`/abandon` disables it for that chat.
Users who never appear in an update cannot be discovered retroactively with the Bot API.

Administrator commands:

- `/coroner`: Show module-wide statistics across all moderated chats, state, dry-run
  mode, reference account, untracked percentage, grades, queue size/oldest wait,
  removals in 30 days, and up to five recent errors. Available in a private chat with
  the bot or a moderated group. The **Update** button refreshes the same global summary
  by editing the message without clearing errors.
- `/coroner help`: Show command descriptions. Other subcommands return their own
  result or view without appending the global summary.
- `/coroner ref <user ID>`: Save a live reference account and this chat as its lookup
  context. This stops the module and requires a subsequent start.
- `/coroner start`: Verify the reference and start checks in all moderated chats.
- `/coroner stop`: Stop checks, preserving the roster and queue. An emergency error stays latched.
- `/coroner run G1|G2|G3|G4|ALL`: Queue checks across all moderated chats for users in
  the selected global grade. Requires a running module; also available in private chats.
- `/coroner detectors`: Show rule settings, sample sufficiency, current values, trigger
  progress, and historical minimum/maximum/mean; also available through **Detectors**.
- `/coroner quarantine`: Browse quarantined accounts with grades, remaining quarantine
  time and direct **Open profile** links on the same page. If Telegram removes a profile
  link, it is labelled **Profile link unavailable**, with the ID formatted for copying.
- `/coroner review`: Review a persisted snapshot, select accounts, approve, reject or
  request fresh checks. Also available from service notifications.
- `/coroner acknowledge`: Release a safety incident after its quarantine is empty and
  its detectors are no longer triggered. Removal budgets are preserved.

Subcommands and grade names ignore case. All Coroner commands and Update require
administrator access to **every** moderated chat, using the existing Swynca provider
or Telegram administrators with `--no-swynca`. In private chats Telegram permissions
are checked in those groups, never in the private conversation. `start` and `stop`
are also available in private chats. Set `ref` inside a moderated group to supply its
lookup context.
The reference need only be known in its saved lookup chat; it need not belong to every group.

Monitored users and grade counts deduplicate user IDs across chats. Removal statistics
also count each user once during the last 30 days, using the grade recorded on their
first removal in that window; individual chat removals remain in the history. The
untracked percentage is `(total memberships - observed memberships) / total memberships`,
using the sum of Telegram member counts, including bots, because the API cannot identify overlapping
unobserved users. If any chat's count is unavailable or inconsistent, the aggregate
percentage is unavailable rather than reporting a partial result.

`<DATA_FOLDER_PATH>/coroner_config.json` is created automatically on first startup
(default: `data/coroner_config.json`). No manual file creation is needed:

```json
{
  "dry_run": false,
  "max_requests_per_minute": 450,
  "reference_check_every": 10,
  "reference_user_id": null,
  "reference_chat_id": null,
  "retry_delay_seconds": 60,
  "grades": [
    {"name": "G1", "max_age_seconds": 86400, "check_interval_seconds": 1800},
    {"name": "G2", "max_age_seconds": 604800, "check_interval_seconds": 7200},
    {"name": "G3", "max_age_seconds": 2592000, "check_interval_seconds": 86400},
    {"name": "G4", "max_age_seconds": null, "check_interval_seconds": 259200}
  ]
}
```

Edit settings while stopped, then use `/coroner start` to reload them. A configured,
live reference is mandatory. Each user has **one global grade**, measured from their
earliest known join or first observation in any moderated chat. Unknown join dates
start at G1 from first observation; confirmed joins use their actual date. A later
join to another chat, a leave/rejoin, or abandoning the first chat does not reset the
global age. Existing per-chat records initialize the global age from the earliest
saved date automatically. The same global grade controls the check interval in every
chat and is recorded on removal. Thresholds and intervals are in seconds.
The shared 450 RPM budget includes checks, reference lookups, UI and retries.

To import known members manually, **shut down the bot process** (not just
`/coroner stop`) and run:

```bash
python3 import_coroner_members.py --chat-id -1001234567890 123456789 987654321
# Or import a text file with user IDs separated by whitespace or commas:
python3 import_coroner_members.py --chat-id -1001234567890 --file members.txt
```

New users start at G1 from the import time. Existing memberships, global ages,
queue and protection state are preserved. The script writes atomically to
`<DATA_FOLDER_PATH>/coroner_state.json` (default: `data/coroner_state.json`);
`--state /path/to/coroner_state.json` selects another file. Restart the bot after
importing. The chat must already be enabled with `/moderate`; import does not start checks.

An account is a removal candidate only when its returned first name is exactly `""`.
Invisible characters remain nonempty. Candidates require confirmation via `getChat`,
a configurable quarantine (**60 minutes** by default), a live reference check, and a
final membership check. Removal kicks the current member
without leaving a permanent ban; previously banned users and administrators are not removed.
Telegram provides no atomic conditional kick: a ban made externally between the final
membership check and the kick cannot be completely ruled out.

`PARTICIPANT_ID_INVALID` during a participant check or removal excludes that user
globally from Coroner's roster, queue and quarantine. The exclusion persists in
`coroner_state.json` as `excluded_user_ids`; observation and manual imports skip it.
This excludes the user from monitoring and does not kick them or count as a removal.
Reference-account failures keep their existing protection behavior. Other API errors
are retried normally. Removal history, safety incidents and budget evidence are retained.

The reference is checked before starting, after every configured number of ordinary
checks, and before every intended removal, including dry runs. A reference detected as
deleted sets `error`, emits a `CRITICAL` log, and blocks work until an explicit successful
`/coroner start`. API errors do not imply deletion; unverifiable references block further work
until verification succeeds. Restarting or changing the reference does not clear an emergency.

With `dry_run: true`, the same checks and safeguards run, but removal only writes a
`CORONER dry_run: would remove ...` log. Members remain in the roster, checks are rescheduled,
and actual removal statistics stay unchanged. With `false` (the default), confirmed kicks
are enabled only after explicitly starting the module.

`coroner_state.json` stores the per-chat roster, global user ages and first-chat IDs,
queue timestamps, control state and actual removal history. Both JSON files use
atomic replacement. An interrupted kick whose
outcome cannot be confirmed is not counted as successful. Status errors remain in memory
only, retain at most five entries across the module with chat context, expire seven
days after their last occurrence, and are lost on process restart;
neither expiry nor Update clears the persisted emergency state.

Coroner additionally blocks automatic removals on deletion-profile spikes, unusually
many daily candidates, recently alive profiles becoming deleted,
contradictory profiles, or a new message from a quarantined account. Rules with too few
observations explicitly show **Check disabled: insufficient data**. Quarantine and
safety incidents persist across restarts; normal checks continue during a safety block.
Service subscribers with current administrator access to every moderated chat receive
review notifications. Approval covers the snapshot's exact accounts and memberships;
it cannot skip quarantine, fresh checks, or removal budgets. A subsequent incident
invalidates earlier approval grants.

The `protection` section is added to valid existing configurations automatically.
See [Coroner protection configuration](docs/coroner-protection.md) for every setting,
initial thresholds, historical statistics, and the review workflow.

## Environment Variables

The following environment variables are used to configure the bot:

- `TELEGRAM_BOT_TOKEN`: Token for authenticating the Telegram bot
- `OPENAI_API_KEY`: API key for accessing OpenAI services (Optional)
- `OPENAI_BASE_URL`: Alternate OpenAI-compatible API URL (Optional, useful for local testing)
- `OPENAI_PROXY_URL`: Proxy URL for OpenAI requests (Optional)
- `OPENAI_WATCHDOG_INTERVAL_SECONDS`: OpenAI availability check interval (Optional, default: `3600`)
- `DEVELOPMENT_MODE`: Enable development-only behavior without the `--development` flag (Optional, default: `false`)
- `DEVELOPMENT_SPAM_BAN_DELAY_SECONDS`: Spam restriction-to-ban delay in development mode (Optional, default: `5`)
- `DEVELOPMENT_UNBAN_DELAY_SECONDS`: Ban-to-unban delay in development mode (Optional, default: `5`)
- `TELEGRAM_API_URL`: Base URL for Telegram API (Optional, default: 'https://api.telegram.org')
- `WEBHOOK_PORT`: Port on which the webhook server will run (Optional, default: `8000`)
- `DATA_FOLDER_PATH`: Path to the data files directory (Optional, default: `data`)
- `LOCALE_FOLDER_PATH`: Path to locale files (Optional, defaults to `<DATA_FOLDER_PATH>/locale`; the Docker image uses `/app/locales`)
- `SWYNCA_API_KEY`: API key for accessing Swynca (Optional if --no-swynca flag is used)
- `TESSERACT_PATH`: Path to the tesseract executable (Optional, default: '/usr/bin/tesseract')
- `TESSERACT_LANG`: Language code for tesseract OCR (Optional, default: 'rus')

Locale files are bundled outside `/app/data` in the Docker image. Updating and recreating the container therefore
loads the locale files from the new image even when `/app/data` is mounted as a persistent volume. Set
`LOCALE_FOLDER_PATH=/app/data/locale` explicitly only if locale files should be managed in the volume instead.

## OpenAI prompt configuration

The `prompt` field in `data/openai_config.json` selects either the prompt bundled with the application:

```json
{
  "prompt": "default"
}
```

or a custom prompt stored in the persistent configuration:

```json
{
  "prompt": "custom",
  "custom_prompt": "Analyze this message for spam..."
}
```

In `default` mode, the current prompt from `src/handlers/spam_filters/openai/OpenAIConfig.py` is used, so prompt
updates are applied when the container image is updated. Legacy configurations containing the prompt text directly in
the `prompt` field are migrated to `custom` automatically on startup.

The default classifier uses `gpt-5.6-luna` through the Responses API with strict Structured Outputs,
`reasoning_effort: "low"`, and `text_verbosity: "low"`. The model receives the target message, OCR transcription,
replied-to message, and the recorded history of edits to the first message.
Configurations still using the previous default model, `gpt-4o-mini`, are migrated to `gpt-5.6-luna` on startup.

## Healthcheck endpoint

- `GET /api/health`
- Returns `200` with `{"telegram_api":"available"}` when Telegram Bot API is reachable.
- Returns `500` with `{"telegram_api":"unavailable"}` when Telegram Bot API is unreachable.
- Availability is checked in background every 10 seconds in both polling and webhook modes.

## Contribution

For guidelines on how to contribute to this project, please see the [CONTRIBUTING.md](CONTRIBUTING.md) file.
