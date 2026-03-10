import asyncio
import os
import threading
from argparse import ArgumentParser
from multiprocessing.managers import Namespace

from telegram import Update
from telegram.ext import Application

from src.AppStarter import get_telegram_application_webhook, get_webserver, get_telegram_application_polling, BotBuilder
from src.telegram.TelegramApiStatusService import TelegramApiStatusService
from src.util.LoggerUtil import LoggerUtil

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
    telegram_api_status_service = TelegramApiStatusService()
    bot_builder = BotBuilder()
    bot_builder.telegram_application = telegram_application
    bot_builder.workdir = WORKDIR
    __set_admin_provider(bot_builder)
    bot_builder.build()
    telegram_api_status_service.start(telegram_application)
    if args.polling:
        logger.info("Starting polling")
        webserver = get_webserver(PORT, WEBHOOK_HOST, telegram_api_status_service)
        webserver_thread = __start_webserver_in_thread(webserver)
        try:
            telegram_application.run_polling(allowed_updates=Update.ALL_TYPES)
        finally:
            __stop_webserver(webserver, webserver_thread)
            telegram_api_status_service.stop()
        return
    logger.info("Starting webhook")
    try:
        asyncio.run(start_webhook(telegram_application, telegram_api_status_service))
    finally:
        telegram_api_status_service.stop()


async def start_webhook(telegram_application: Application, telegram_api_status_service: TelegramApiStatusService):
    await telegram_application.bot.set_webhook(url=f"{WEBHOOK_HOST}/telegram", allowed_updates=Update.ALL_TYPES)
    webserver = get_webserver(PORT, WEBHOOK_HOST, telegram_api_status_service, telegram_application)
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


def __start_webserver_in_thread(webserver) -> threading.Thread:
    webserver_thread = threading.Thread(target=webserver.run, daemon=True)
    webserver_thread.start()
    return webserver_thread


def __stop_webserver(webserver, webserver_thread: threading.Thread):
    webserver.should_exit = True
    webserver_thread.join(timeout=5)


if __name__ == "__main__":
    main()
