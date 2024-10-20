# bksp-antispam-bot
# B4CKSP4CE Telegram Antispam Bot

## Description

The B4CKSP4CE Telegram Antispam Bot is designed to help manage and moderate Telegram chats by automatically detecting and handling spam messages. It uses a combination of predefined filters and AI-based analysis to ensure that your chat remains free from unwanted content.

## Modules Used

- **Flask**: Used for creating a web server to handle incoming Telegram updates.
- **Uvicorn**: ASGI server for running the web application.
- **Python Telegram Bot**: Provides a framework for building Telegram bots.
- **OpenAI**: Utilized for AI-based spam detection.
- **Pydantic**: Used for data validation and settings management.
- **Requests**: For making HTTP requests to external APIs.

## How It Moderates Messages

The bot uses a chain of spam filters to evaluate each incoming message. These filters can be simple rule-based checks or more complex AI-driven analyses. If a message is identified as spam, the bot can take actions such as deleting the message or banning the user.

## Environment Variables

The following environment variables are used to configure the bot:

- `OPENAI_API_KEY`: API key for accessing OpenAI services.
- `OPENAI_PROXY_URL`: Proxy URL for OpenAI requests.
- `TELEGRAM_API_URL`: Base URL for Telegram API.
- `TELEGRAM_BOT_TOKEN`: Token for authenticating the Telegram bot.
- `WEBHOOK_PORT`: Port on which the webhook server will run.
- `CONFIG_FOLDER_PATH`: Path to the configuration files.
- `SWYNCA_API_KEY`: API key for accessing Swynca services.
