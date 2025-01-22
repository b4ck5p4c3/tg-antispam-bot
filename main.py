import asyncio
import os
from argparse import ArgumentParser
from multiprocessing.managers import Namespace

from telegram.ext import MessageHandler, filters, CommandHandler, ChatMemberHandler, Application
from telegram import Update

from src.AppStarter import get_telegram_application_webhook, get_webserver, get_telegram_application_polling, BotBuilder
from src.handlers.ConfigurationCommandsHandler import ConfigurationCommandsHandler
from src.handlers.LolsOnJoinSpamCheck import LolsOnJoinSpamCheck
from src.handlers.spam_filters.FilterFactory import FilterFactory
from src.handlers.spam_filters.lols.LolsSpamFilter import LolsSpamFilter
from src.handlers.spam_filters.openai.OpenAISpamFilter import OpenAIFilterConfig
from src.locale.LocaleFactory import LocaleFactory
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.admin.AdminProvider import AdminProvider
from src.util.LoggerUtil import LoggerUtil
from src.util.admin.SwyncaAdminProvider import SwyncaAdminProvider
from src.util.config.Config import Config
from src.util.config.JsonModelRepo import JsonModelRepo

URL = os.getenv("TELEGRAM_API_URL", "https://api.telegram.org")
PORT = int(os.getenv("WEBHOOK_PORT", 8000))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WORKDIR = os.path.dirname(os.path.abspath(__file__))
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")

argument_parser: ArgumentParser = ArgumentParser()
argument_parser.add_argument("--polling", dest="polling", default=False, action="store_true")
argument_parser.add_argument("--no-swynca", dest="no_swynca", default=False, action="store_true")
args: Namespace = argument_parser.parse_args()


def main():
    logger = LoggerUtil.get_logger("AppStarter", "main")
    telegram_application: Application = __get_application(args.polling)
    bot_builder = BotBuilder()
    bot_builder.telegram_application = telegram_application
    bot_builder.workdir = WORKDIR
    __set_admin_provider(bot_builder)
    bot_builder.build()
    if args.polling:
        logger.info("Starting polling")
        telegram_application.run_polling(allowed_updates=Update.ALL_TYPES)
    else:
        logger.info("Starting webhook")
        asyncio.run(start_webhook(telegram_application))


async def start_webhook(telegram_application: Application):
    await telegram_application.bot.set_webhook(url=f"{WEBHOOK_HOST}/telegram", allowed_updates=Update.ALL_TYPES)
    webserver = get_webserver(PORT, WEBHOOK_HOST, telegram_application)
    async with telegram_application:
        await telegram_application.start()
        await webserver.serve()
        await telegram_application.stop()

def __get_application(polling: bool) -> Application:
    if polling:
        return get_telegram_application_polling(TOKEN, URL)
    return get_telegram_application_webhook(TOKEN, URL)

def __set_admin_provider(bot_builder: BotBuilder):
    if args.no_swynca:
        bot_builder.channel_admin_provider()
        return
    bot_builder.swynca_admin_provider()

if __name__ == "__main__":
    main()
