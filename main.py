#!/usr/bin/env python
# This program is dedicated to the public domain under the CC0 license.
# pylint: disable=import-error,unused-argument
"""
Simple example of a bot that uses a custom webhook setup and handles custom updates.
For the custom webhook setup, the libraries `flask`, `asgiref` and `uvicorn` are used. Please
install them as `pip install flask[async]~=2.3.2 uvicorn~=0.23.2 asgiref~=3.7.2`.
Note that any other `asyncio` based web server framework can be used for a custom webhook setup
just as well.

Usage:
Set bot Token, URL, admin CHAT_ID and PORT after the imports.
You may also need to change the `listen` value in the uvicorn configuration to match your setup.
Press Ctrl-C on the command line or send a signal to the process to stop the bot.
"""
import asyncio
import os
from http import HTTPStatus

import telegram
import uvicorn
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, Response, request
from telegram import Update, ChatPermissions, Message
from telegram.ext import (
    Application,
    CallbackContext,
    MessageHandler, filters, CommandHandler,
)

from modules.ModulesFactory import ModulesFactory
from util.JsonDB import JsonDB
from util.LoggerUtil import LoggerUtil

# Define configuration constants
URL = os.getenv("TELEGRAM_API_URL")
PORT = int(os.getenv("WEBHOOK_PORT", 8000))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATA_PATH = os.getenv("DATA_PATH", "data")
ADMINS = [int(admin_id) for admin_id in os.getenv("ADMINS").split(",")] #TODO: replace to swinca api request when Ehor is done with it

TRUSTED_USERS_DB = JsonDB("{}/trusted_users.json".format(DATA_PATH))
TRUSTED_USERS = TRUSTED_USERS_DB.read_or_default([])

CONFIG_DB = JsonDB("{}/config.json".format(DATA_PATH))
CONFIG = CONFIG_DB.read_or_default({"chats_to_moderate": []})



logger = LoggerUtil.get_logger("BOT")

filters_by_priority = ModulesFactory.get_all_mapped_by_priority(logger)

async def check_message_for_spam(update: Update, context: CallbackContext) -> None:
    try:
        if update.message.from_user.id in TRUSTED_USERS or update.message.chat_id not in CONFIG["chats_to_moderate"]:
            return
        message = update.message
        logger.info("Received message: %s", message.text)
        for priority in filters_by_priority.keys():
            for a_filter in filters_by_priority[priority]:
                is_spam = a_filter.is_spam(update)
                if is_spam:
                    logger.info("Message from user %d detected as spam by %s. Restricting..", message.from_user.id, a_filter.__class__.__name__)
                    await context.bot.delete_message(chat_id=message.chat_id, message_id=message.message_id)
                    await restrict_user(message.from_user, message.chat_id, "Detected as spam by {}".format(a_filter.__class__.__name__), context)
                    context.job_queue.run_once(ban_message_author, 60*10, data=message)
                    return
        logger.info("Message is not spam")
        TRUSTED_USERS.append(message.from_user.id)
        TRUSTED_USERS_DB.write(TRUSTED_USERS)
    except Exception as e:
        logger.error("Error while checking message for spam: %s", e)


def admin_command(func):
    async def wrapper(update: Update, context: CallbackContext) -> None:
        if update.message.from_user.id not in ADMINS:
            await context.bot.send_message(chat_id=update.message.chat_id, text="You are not an admin")
            return
        return await func(update, context)
    return wrapper


@admin_command
async def add_chat_to_moderate(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id
    if chat_id in CONFIG["chats_to_moderate"]:
        await context.bot.send_message(chat_id=chat_id, text="Chat is already moderable")
        return
    CONFIG["chats_to_moderate"].append(chat_id)
    CONFIG_DB.write(CONFIG)
    await context.bot.send_message(chat_id=chat_id, text="Chat added to moderable chats")

async def ban_message_author(context: CallbackContext) -> None:
    """kick user who sent the message from context.job.data"""
    message: Message = context.job.data
    logger.info("Banning user %d", message.from_user.id)
    await context.bot.ban_chat_member(chat_id=message.chat_id, user_id=message.from_user.id)

async def restrict_user(user: telegram.User, chat_id: int, reason: str, context: CallbackContext) -> None:
    logger.info("Banning user %d for reason: %s", user.id, reason)
    await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user.id, permissions=ChatPermissions(can_send_messages=False))
    message = await context.bot.send_message(chat_id=chat_id,
                                   parse_mode="Markdown",
                                   text="[{user.first_name}](tg://user?id={user.id}) You have been restricted. Message: {reason}.\n\n If this is an error, write to any admin of this chat. Your account will be kicked in 10 minutes".format(user=user, reason=reason))
    context.job_queue.run_once(delete_message, 20, data=message)

async def delete_message(context: CallbackContext) -> None:
    message_to_delete: Message = context.job.data
    await context.bot.delete_message(chat_id=message_to_delete.chat_id, message_id=message_to_delete.message_id)

def get_user_tag_or_id(user: telegram.User) -> str:
    return user.username if user.username else str(user.id)



async def main() -> None:
    application = (
            Application.builder().token(TOKEN).base_url(f"{URL}/bot").updater(None).build()
    )

    application.add_handler(CommandHandler("moderate", add_chat_to_moderate))

    application.add_handler(MessageHandler(filters.ALL, check_message_for_spam))

    await application.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)
    flask_app = Flask(__name__)

    @flask_app.post("/telegram")
    async def telegram() -> Response:
        await application.update_queue.put(Update.de_json(data=request.json, bot=application.bot))
        return Response(status=HTTPStatus.OK)

    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=WsgiToAsgi(flask_app),
            port=PORT,
            use_colors=False,
            host="0.0.0.0",
        )
    )

    async with application:
        await application.start()
        await webserver.serve()
        await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
