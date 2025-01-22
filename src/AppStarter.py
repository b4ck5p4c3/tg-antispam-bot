import os
from http import HTTPStatus

import uvicorn
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, Response, request
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ChatMemberHandler, ApplicationBuilder

from src.handlers.ConfigurationCommandsHandler import ConfigurationCommandsHandler
from src.handlers.LolsOnJoinSpamCheck import LolsOnJoinSpamCheck
from src.handlers.spam_filters.FilterFactory import FilterFactory
from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.handlers.spam_filters.lols.LolsSpamFilter import LolsSpamFilter
from src.handlers.spam_filters.openai.OpenAISpamFilter import OpenAIFilterConfig
from src.locale.LocaleFactory import LocaleFactory
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.LoggerUtil import LoggerUtil
from src.util.admin.AdminProvider import AdminProvider
from src.util.admin.ChannelAdminProvider import ChannelAdminProvider
from src.util.admin.SwyncaAdminProvider import SwyncaAdminProvider
from src.util.config.Config import Config
from src.util.config.JsonModelRepo import JsonModelRepo
from telegram import Update


def __get_telegram_application_builder(token: str, base_url: str) -> ApplicationBuilder:
    return (Application.builder()
     .token(token)
     .base_url(f"{base_url}/bot")
     .base_file_url(f"{base_url}/file/bot"))

def get_telegram_application_webhook(token: str, base_url: str) -> Application:
    return __get_telegram_application_builder(token, base_url).updater(None).build()

def get_telegram_application_polling(token: str, base_url: str) -> Application:
    return __get_telegram_application_builder(token, base_url).build()


def get_webserver(server_port: int, host: str, telegram_application) -> uvicorn.Server:
    flask_app = Flask(__name__)

    @flask_app.post("/telegram")
    async def telegram() -> Response:
        await telegram_application.update_queue.put(Update.de_json(data=request.json, bot=telegram_application.bot))
        return Response(status=HTTPStatus.OK)

    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=WsgiToAsgi(flask_app),
            port=server_port,
            use_colors=False,
            host=host
        )
    )
    return webserver





class BotBuilder:
    workdir = os.path.dirname(os.path.abspath(__file__))
    __admin_provider_supplier = None
    telegram_application: Application = None

    def __with_enriched_update(self, runnable):
        async def wrapper(update, context):
            enriched_update = EnrichedUpdate.from_update(update, self.__get_locale_factory())
            await runnable(enriched_update, context)
        return wrapper

    def __get_locale_factory(self):
        return LocaleFactory(os.path.join(self.__get_config_folder_path(), "locale"))

    def __get_config_folder_path(self):
        return os.getenv("CONFIG_FOLDER_PATH", os.path.join(self.workdir, "data"))


    def swynca_admin_provider(self):
        self.__admin_provider_supplier = self.__get_swynca_admin_provider
        return self

    def channel_admin_provider(self):
        self.__admin_provider_supplier = self.__get_channel_admin_provider
        return self


    def build(self):
        if self.telegram_application is None:
            raise ValueError("Telegram application is not set")
        config = self.__get_config()
        antispam_filters: SpamFilter = self.__get_antispam_filter_chain(config)
        lols_spam_filter = LolsSpamFilter(config)

        configuration_commands_handler: ConfigurationCommandsHandler = ConfigurationCommandsHandler(config)
        lols_on_join_spam_check: LolsOnJoinSpamCheck = LolsOnJoinSpamCheck(config, lols_spam_filter)

        self.telegram_application.add_handler(CommandHandler("moderate", self.__with_enriched_update(configuration_commands_handler.handle_add_moderable_chat)))
        self.telegram_application.add_handler(CommandHandler("stop_moderate", self.__with_enriched_update(configuration_commands_handler.handle_remove_moderable_chat)))
        self.telegram_application.add_handler(MessageHandler(filters.ALL, self.__with_enriched_update(antispam_filters.apply)))
        self.telegram_application.add_handler(ChatMemberHandler(self.__with_enriched_update(lols_on_join_spam_check.handle_user_join),
                                                           ChatMemberHandler.CHAT_MEMBER))

    def __get_config(self) -> Config:
        admin_provider: AdminProvider = self.__admin_provider_supplier()
        config_path = os.path.join(self.__get_config_folder_path(), "config.json")
        config_repo: JsonModelRepo[Config] = JsonModelRepo(config_path)
        config: Config = Config.load_from_file(admin_provider, config_repo)
        return config

    def __get_swynca_admin_provider(self) -> AdminProvider:
        return SwyncaAdminProvider(LoggerUtil.get_logger("AdminProvider", "SwyncaAdminProvider"))

    def __get_channel_admin_provider(self) -> AdminProvider:
        return ChannelAdminProvider(LoggerUtil.get_logger("AdminProvider", "ChannelAdminProvider"), self.telegram_application.bot)

    def __get_antispam_filter_chain(self, config: Config) -> SpamFilter:
        openai_config_path = os.path.join(self.__get_config_folder_path(), "openai_config.json")
        openai_config: OpenAIFilterConfig = JsonModelRepo(openai_config_path).load(OpenAIFilterConfig,
                                                                                   OpenAIFilterConfig())
        return FilterFactory.get_default_chain(config, openai_config)


