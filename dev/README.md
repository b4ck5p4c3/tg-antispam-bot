# Telethon userbot debugger

`userbot.py` logs in as a regular Telegram user, sends commands to the installed antispam bot, and traces the bot's new, edited, and deleted messages. It is intended for an isolated development chat.

## Setup

Install the application and development dependencies:

```bash
.venv/bin/pip install -r requirements.txt -r dev/requirements.txt
```

Create an application at [my.telegram.org](https://my.telegram.org/) to obtain a Telegram API ID and API hash. Telethon's [sign-in guide](https://docs.telethon.dev/en/stable/basic/signing-in.html) explains these credentials and the persistent session, after which the userbot can be started:

```bash
.venv/bin/python dev/userbot.py
```

On the first run it asks for:

1. Telegram API ID and API hash.
2. The antispam bot username.
3. An optional test group username or ID. Use a group where the user account is an admin so `/as_service` commands pass the bot's admin check.
4. The phone number, login code, and 2FA password when required by Telethon.

The API credentials and selected entities are saved in `dev/userbot_config.json`; authorization is saved in `dev/userbot.session`. Both files and all debug logs are ignored by Git. The config file is created with user-only permissions when the operating system supports them.

The following environment variables can supply or override the interactive configuration:

- `TELETHON_API_ID`
- `TELETHON_API_HASH`
- `ANTISPAM_BOT_USERNAME`
- `ANTISPAM_TEST_CHAT`

## Useful commands

- `service subscribe|unsubscribe|list` sends the corresponding `/as_service` command.
- `scenario subscription` verifies subscription, duplicate subscription, listing, unsubscription, and duplicate unsubscription.
- `scenario watchdog [timeout]` subscribes, waits for an OpenAI outage notification, and then verifies that the same message is edited after recovery.
- `send <text>` and `reply <message_id> <text>` send test messages.
- `report <message_id>` exercises the existing report flow.
- `target <username|ID>` changes the test chat.
- `dialogs` and `history [target|bot] [limit]` help locate chats and inspect messages.
- `raw on|off` toggles raw Telegram updates in the terminal. Raw updates are always available in `dev/userbot_debug.log`.
- `watch [seconds]` keeps the event listener running without accepting commands.

Run `help` in the interactive console for the complete list. The same scenarios can be started non-interactively after configuration:

```bash
.venv/bin/python dev/userbot.py --scenario subscription
.venv/bin/python dev/userbot.py --scenario watchdog --watchdog-timeout 180
```

## Testing the OpenAI watchdog

The production watchdog interval is one hour. For a local test, start the bot with a shorter interval:

```bash
.venv/bin/python dev/openai_mock.py --initial-state fail
```

In a second terminal, point the bot at the mock and use a shorter interval:

```bash
set -a
source .env
set +a
OPENAI_API_KEY=test \
OPENAI_BASE_URL=http://127.0.0.1:8123/v1 \
OPENAI_WATCHDOG_INTERVAL_SECONDS=5 \
.venv/bin/python main.py --polling --no-swynca
```

Then:

1. Run `scenario watchdog 180` in the userbot.
2. Keep the mock in its initial `fail` state and wait for the quota-error notification.
3. Wait for the private service notification containing the connection or API error.
4. Enter `ok` in the mock console without restarting the bot.
5. The next successful check should edit the original notification, strike out the failure text, and add the recovery signature.

To test failure detection during spam processing, send a message from a separate untrusted, non-admin account while OpenAI is unavailable. The service subscriber itself is normally an admin and is skipped by the spam filter.

Use only disposable development chats and accounts: report and moderation commands can delete messages or restrict users.
