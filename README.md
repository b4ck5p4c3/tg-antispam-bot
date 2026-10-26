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
Every edit is checked again. While the user is tracked by Coroner and is not trusted,
recorded earlier versions (text/caption, OCR transcription, and reply context) are included in the AI request.
Saved context is discarded when the user becomes trusted or leaves Coroner monitoring.
Trusted users retain only the message ID and edit counters, without earlier message contents.
Counters are also removed when monitoring ends. State is persisted in `data/state.json` across restarts.
Admins, anonymous admins, linked-channel automatic forwards, and chats without moderation remain exempt.

Set `max_message_edits` in `data/openai_config.json` to change the edit limit (default: `10`; minimum: `0`).
Edits 1–10 are checked normally; edit 11 deletes the message and bans its author immediately, before OCR or any
external spam checks. Restart the bot after changing the configuration.
For users already trusted before edit counting was enabled, the first observed edit starts counting that message.
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
- `/mute [user ID|@username] [duration]`: Mute a user in the current supergroup, or reply to their message; duration defaults to `1d`
- `/unmute [user ID|@username]`: Lift a mute in the current supergroup, or reply to the user's message
- `/banc`: Restrict reposting of messages from the chat (only first message)
- `/report`: Report spam and manage report notification subscriptions
- `/as_service`: Manage service notification subscriptions
- `/set_audit_log`: Set chat for [audit logging](#audit-logging)
- `/unset_audit_log`: Unset chat for audit logging

Mute commands require administrator access in the current chat and the bot's permission to restrict members.
They set the user to read-only, disabling messages, media, polls, reactions, invites, pins, topic management,
chat changes, and member-tag editing. `/unmute` lifts individual restrictions; the chat's default permissions
still apply. Administrators, anonymous senders, channels, and users outside the chat cannot be muted.

Durations use a positive integer and one unit: `s`/`S` (seconds), `m` (minutes), `h`/`H` (hours),
`d`/`D` (days), `w`/`W` (weeks), `M` (30-day months), `y`/`Y` (365-day years), or `c`/`C` (100 years).
Examples: `/mute @username 3h`, `/mute 123456789 451d`, `/mute 5S` as a reply.
When duration is omitted, `/mute @username`, `/mute 123456789`, and `/mute` as a reply mute for `1d`.
An explicit user always overrides the replied message, for both `/mute` and `/unmute`.
Username lookup uses the saved user cache and verifies the current username before acting.
Muting and unmuting leave permanent confirmation messages and audit entries.

Durations shorter than 30 seconds are increased to 30 seconds; the confirmation and audit entry explain
Telegram's minimum.
Durations over one year (365 days) create a permanent restriction, while confirmations and audit entries
show the requested duration (for example, `50 years`). Other mutes expire through Telegram, even if the bot
is offline. No local expiry jobs or mute state are stored.
Reaction restrictions require a Bot API server supporting `can_react_to_messages` (Bot API 10.0 or newer).

## Audit logging

The bot logs successful `/ban`, `/mute`, and `/unmute` commands in the chat configured for audit logging.
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

Coroner tracks members observed in moderated groups and periodically checks for deleted
accounts. Confirmed deleted accounts are permanently banned after quarantine. A live
reference account, anomaly detection and removal limits protect against false positives;
suspicious cases require administrator review. Telegram cannot list all existing members,
so monitoring begins when the bot observes a user.

The module starts stopped on first launch. Set a live reference account with
`/coroner ref <user ID>` in a moderated group, then use `/coroner start` to enable checks.
`/coroner stop` pauses checks. Commands require administrator access to every moderated chat.

Use `/coroner` for status, `/coroner quarantine` to view pending accounts and
`/coroner review` to review safety alerts.

Settings are stored in `data/coroner_config.json`; `dry_run: true` enables checks without
banning users. Monitoring state and module status persist across restarts in SQLite.

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
