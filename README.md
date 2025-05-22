# B4CKSP4CE Telegram Antispam Bot

## Description

The B4CKSP4CE Telegram Antispam Bot is designed to help manage and moderate Telegram chats by automatically detecting and handling spam messages. It uses a combination of predefined filters and AI-based analysis to ensure that your chat remains free from unwanted content.
Bot using webhooks to receive messages from Telegram and OpenAI API to analyze messages

## How It Moderates Messages

The bot uses a chain of spam filters to evaluate each incoming message. These filters can be simple rule-based checks or more complex AI-driven analyses. If a message is identified as spam, the bot can take actions such as deleting the message or banning the user

## How to run it without B4CKSP4CE infrastructure

1. Clone the repository and navigate to the project directory `cd tg_antispam_bot`
2. Build the Docker image using `docker build -t tg_antispam_bot .`
3. Run the bot using `docker run --env TELEGRAM_BOT_TOKEN=<BOT_TOKEN> -v data:/app/data tg_antispam_bot --polling --no-swynca`.
4. Enable moderation in the chat by sending `/moderate` command.
Optionally, you can provide the `OPENAI_API_KEY` env variable for filtering messages using OpenAI API.

## Available commands

- `/moderate`: Add chat to the list of moderated chats
- `/abandon`: Remove chat from the list of moderated chats
- `/ban`: Ban user from the chat
- `/banc`: Restrict reposting of messages from the chat (only first message)
- `/set_audit_log`: Set chat for [audit logging](#audit-logging)
- `/unset_audit_log`: Unset chat for audit logging

## Audit logging

The bot will log all usage of the `/ban` command in the chat configured for audit logging.
By default, logs are saved in the chat where the command was executed. However, you can specify a different chat for logging by using the `/set_audit_log` command.

⚠ Topics are not supported in audit logs. If you want to use audit logging, make sure to disable topics in the chat.

## Run arguments

- `--polling`: Use polling instead of webhooks
- `--no-swynca`: Disable Swynca for admin list providing, use message chat admins instead

## Environment Variables

The following environment variables are used to configure the bot:

- `TELEGRAM_BOT_TOKEN`: Token for authenticating the Telegram bot
- `OPENAI_API_KEY`: API key for accessing OpenAI services (Optional)
- `OPENAI_PROXY_URL`: Proxy URL for OpenAI requests (Optional)
- `TELEGRAM_API_URL`: Base URL for Telegram API (Optional, default: 'https://api.telegram.org')
- `WEBHOOK_PORT`: Port on which the webhook server will run (Optional, default: `8000`)
- `CONFIG_FOLDER_PATH`: Path to the configuration files directory (Optional, default: `config`)
- `SWYNCA_API_KEY`: API key for accessing Swynca (Optional if --no-swynca flag is used)
- `TESSERACT_PATH`: Path to the tesseract executable (Optional, default: '/usr/bin/tesseract')
- `TESSERACT_LANG`: Language code for tesseract OCR (Optional, default: 'rus')
## Contribution

For guidelines on how to contribute to this project, please see the [CONTRIBUTING.md](CONTRIBUTING.md) file.
