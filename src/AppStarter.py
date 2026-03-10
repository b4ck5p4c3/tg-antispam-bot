import os
from http import HTTPStatus

import uvicorn
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, Response, request
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ApplicationBuilder, CallbackQueryHandler, TypeHandler, ChatMemberHandler

from src.handlers.ButtonClickHandler import ButtonClickHandler
from src.handlers.CacheHandler import CacheHandler
from src.handlers.ConfigurationCommandsHandler import ConfigurationCommandsHandler
from src.handlers.ManualModerationCommandsHandler import ManualModerationCommandsHandler
from src.handlers.ReportCommandsHandler import ReportCommandsHandler
from src.handlers.spam_filters.FilterFactory import FilterFactory
from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.handlers.spam_filters.openai.OpenAISpamFilter import OpenAIFilterConfig
from src.locale.LocaleFactory import LocaleFactory
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.LoggerUtil import LoggerUtil
from src.util.admin.AdminProvider import AdminProvider
from src.util.admin.ChannelAdminProvider import ChannelAdminProvider
from src.util.admin.SwyncaAdminProvider import SwyncaAdminProvider
from src.util.data.BotState import BotState
from src.util.data.JsonModelRepo import JsonModelRepo
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
        return LocaleFactory(os.path.join(self.__get_data_folder_path(), "locale"))

    def __get_data_folder_path(self):
        return os.getenv("DATA_FOLDER_PATH", os.path.join(self.workdir, "data"))

    def swynca_admin_provider(self):
        self.__admin_provider_supplier = self.__get_swynca_admin_provider
        return self

    def channel_admin_provider(self):
        self.__admin_provider_supplier = self.__get_channel_admin_provider
        return self

    def build(self):
        if self.telegram_application is None:
            raise ValueError("Telegram application is not set")
        state = self.__get_state()
        antispam_filters: SpamFilter = self.__get_antispam_filter_chain(state)

        configuration_commands_handler: ConfigurationCommandsHandler = ConfigurationCommandsHandler(state)
        manual_commands_handler: ManualModerationCommandsHandler = ManualModerationCommandsHandler(state)
        report_commands_handler: ReportCommandsHandler = ReportCommandsHandler(state)
        cache_handler: CacheHandler = CacheHandler(state)
        button_click_handler: ButtonClickHandler = ButtonClickHandler(state)
        button_click_handler.set_listeners(report_commands_handler)

        self.__add_command_handler("moderate", configuration_commands_handler.handle_add_moderable_chat)
        self.__add_command_handler("abandon", configuration_commands_handler.handle_remove_moderable_chat)
        self.__add_command_handler("set_audit_log", configuration_commands_handler.set_channel_as_audit_log)
        self.__add_command_handler("unset_audit_log", configuration_commands_handler.unset_channel_as_audit_log)
        self.__add_command_handler("ban", manual_commands_handler.handle_ban_user)
        self.__add_command_handler("banc", manual_commands_handler.handle_ban_community)
        self.__add_command_handler("report", report_commands_handler.handle_report_command)
        self.telegram_application.add_handler(
            TypeHandler(Update, self.__with_enriched_update(cache_handler.handle_update)),
            group=-1
        )
        self.telegram_application.add_handler(
            ChatMemberHandler(
                self.__with_enriched_update(report_commands_handler.handle_banned_user_updates),
                chat_member_types=ChatMemberHandler.CHAT_MEMBER
            ),
            group=0
        )
        self.telegram_application.add_handler(
            CallbackQueryHandler(self.__with_enriched_update(button_click_handler.handle_button_click_and_route)))
        self.telegram_application.add_handler(
            MessageHandler(filters.ALL, self.__with_enriched_update(antispam_filters.apply)))

    def __add_command_handler(self, command: str, handler):
        self.telegram_application.add_handler(CommandHandler(command, self.__with_enriched_update(handler)))

    def __get_state(self) -> BotState:
        admin_provider: AdminProvider = self.__admin_provider_supplier()
        state_path = os.path.join(self.__get_data_folder_path(), "state.json")
        state_repo: JsonModelRepo[BotState] = JsonModelRepo(state_path)
        state: BotState = BotState.load_from_file(admin_provider, state_repo)
        return state

    def __get_swynca_admin_provider(self) -> AdminProvider:
        return SwyncaAdminProvider(LoggerUtil.get_logger("AdminProvider", "SwyncaAdminProvider"))

    def __get_channel_admin_provider(self) -> AdminProvider:
        return ChannelAdminProvider(LoggerUtil.get_logger("AdminProvider", "ChannelAdminProvider"),
                                    self.telegram_application.bot)

    def __get_antispam_filter_chain(self, state: BotState) -> SpamFilter:
        openai_config_path = os.path.join(self.__get_data_folder_path(), "openai_config.json")
        openai_config: OpenAIFilterConfig = JsonModelRepo(openai_config_path).load(OpenAIFilterConfig,
                                                                                   OpenAIFilterConfig())
        return FilterFactory.get_default_chain(state, openai_config)
