import asyncio
import os

from telegram.ext import MessageHandler, filters, CommandHandler, ChatMemberHandler
from telegram import Update

from src.AppStarter import get_telegram_application, get_webserver
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

URL = os.getenv("TELEGRAM_API_URL")
PORT = int(os.getenv("WEBHOOK_PORT", 8000))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WORKDIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FOLDER_PATH = os.getenv("CONFIG_FOLDER_PATH", os.path.join(WORKDIR, "data"))
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")


async def main():

    def with_enriched_update(runnable):
        async def wrapper(update, context):
            enriched_update = EnrichedUpdate.from_update(update, locale_factory)
            await runnable(enriched_update, context)
        return wrapper

    logger = LoggerUtil.get_logger("AdminProvider", "AdminProvider")
    admin_provider: AdminProvider = SwyncaAdminProvider(logger)

    config_path = os.path.join(CONFIG_FOLDER_PATH, "config.json")
    config_repo: JsonModelRepo[Config] = JsonModelRepo(config_path)
    config: Config = Config.load_from_file(admin_provider, config_repo)
    openai_config_path = os.path.join(CONFIG_FOLDER_PATH, "openai_config.json")
    openai_config: OpenAIFilterConfig = JsonModelRepo(openai_config_path).load(OpenAIFilterConfig, OpenAIFilterConfig())
    locale_folder_path = os.path.join(CONFIG_FOLDER_PATH, "locale")
    locale_factory = LocaleFactory(locale_folder_path)
    lols_spam_filter = LolsSpamFilter(config)

    antispam_filters = FilterFactory.get_default_chain(config, openai_config)
    configuration_commands_handler: ConfigurationCommandsHandler = ConfigurationCommandsHandler(config)
    lols_on_join_spam_check: LolsOnJoinSpamCheck = LolsOnJoinSpamCheck(config, lols_spam_filter)

    telegram_application = get_telegram_application(TOKEN, URL)
    telegram_application.add_handler(CommandHandler("moderate", with_enriched_update(configuration_commands_handler.handle_add_moderable_chat)))
    telegram_application.add_handler(CommandHandler("stop_moderate", with_enriched_update(configuration_commands_handler.handle_remove_moderable_chat)))
    telegram_application.add_handler(MessageHandler(filters.ALL, with_enriched_update(antispam_filters.apply)))
    telegram_application.add_handler(ChatMemberHandler(with_enriched_update(lols_on_join_spam_check.handle_user_join), ChatMemberHandler.CHAT_MEMBER))
    await telegram_application.bot.set_webhook(url=f"{WEBHOOK_HOST}/telegram", allowed_updates=Update.ALL_TYPES)


    webserver = get_webserver(PORT, WEBHOOK_HOST, telegram_application)


    async with telegram_application:
        await telegram_application.start()
        await webserver.serve()
        await telegram_application.stop()


if __name__ == "__main__":
    asyncio.run(main())
