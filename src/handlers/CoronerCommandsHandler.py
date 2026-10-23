from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.CommandHelp import command_help
from src.coroner.CoronerApi import CoronerInterrupted
from src.coroner.CoronerMessages import coroner_text
from src.coroner.CoronerService import CoronerService
from src.coroner.CoronerProtectionView import CoronerProtectionKeyboardData, CoronerProtectionView
from src.handlers.ButtonClickHandler import button_click
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.telegram.KeyboardData import KeyboardData


class CoronerKeyboardData(KeyboardData):
    key_id: str = "CORONER"


class CoronerCommandsHandler:
    def __init__(self, service: CoronerService):
        self.service = service

    def _keyboard(self, locale):
        rows = [[InlineKeyboardButton(
            coroner_text(locale, "update"), callback_data=CoronerKeyboardData().model_dump(),
        )]]
        rows.extend(CoronerProtectionView(self.service, locale).main_buttons())
        return InlineKeyboardMarkup(rows)

    async def _protection_display(self, update, action, page=0,
                                  notice="", *, edit=False, refresh_links=False):
        if action == "detectors":
            try:
                await self.service.protection.populations()
            except CoronerInterrupted:
                raise
            except Exception:
                pass
        view = CoronerProtectionView(self.service, update.locale)
        await view.display(
            action, page, update.effective_chat.id, notice=notice,
            message_id=update.callback_query.message.message_id if edit else None,
            refresh_links=refresh_links,
        )

    async def _reply(self, update, text):
        chat_id = update.effective_chat.id
        await self.service.api.call(
            self.service.bot.send_message, chat_id=chat_id, text=await self.service.display_text(text),
            parse_mode="HTML", error_chat_id=chat_id,
        )

    async def _display(self, update, *, edit=False):
        chat_id = update.effective_chat.id
        text = await self.service.status_text(update.locale)
        await self.service.account_links.display(
            text, self._keyboard(update.locale), CoronerProtectionView(self.service, update.locale).t,
            chat_id, update.callback_query.message.message_id if edit else None,
        )

    @command_help(
        {'command': 'coroner', 'locale_id': 'help_coroner_status', 'admin': True},
        {'command': 'coroner help', 'locale_id': 'help_coroner_help', 'admin': True},
        {'command': 'coroner ref <user_id>', 'locale_id': 'help_coroner_ref', 'admin': True},
        {'command': 'coroner start', 'locale_id': 'help_coroner_start', 'admin': True},
        {'command': 'coroner stop', 'locale_id': 'help_coroner_stop', 'admin': True},
        {
            "command": 'coroner run <G1|G2|G3|G4|ALL>',
            "locale_id": 'help_coroner_run',
            "admin": True,
        },
        {'command': 'coroner detectors', 'locale_id': 'help_coroner_detectors', 'admin': True},
        {'command': 'coroner quarantine', 'locale_id': 'help_coroner_quarantine', 'admin': True},
        {'command': 'coroner review', 'locale_id': 'help_coroner_review', 'admin': True},
        {'command': 'coroner acknowledge', 'locale_id': 'help_coroner_acknowledge', 'admin': True},
        {'command': 'coroner bypass', 'locale_id': 'help_coroner_bypass', 'admin': True},
        {'command': 'coroner bypass stop', 'locale_id': 'help_coroner_bypass_stop', 'admin': True},
        module="help_module_coroner",
    )
    async def handle_command(self, update: EnrichedUpdate, context: CallbackContext):
        chat = update.effective_chat
        user = update.effective_user
        if chat is None or user is None:
            return
        try:
            if not await self.service.authorized(user.id, chat.id):
                return
            if chat.type != Chat.PRIVATE and (
                    chat.type not in (Chat.GROUP, Chat.SUPERGROUP)
                    or not self.service.bot_state.is_chat_moderated(chat.id)):
                await self._reply(update, coroner_text(update.locale, "group_only"))
                return
            args = context.args or []
            if not args:
                await self._display(update)
                return
            action = args[0].casefold()
            notice = ""
            if action in ("detectors", "quarantine", "review") and len(args) == 1:
                await self._protection_display(update, action, refresh_links=True)
                return
            valid = ((action in ("help", "start", "stop", "acknowledge") and len(args) == 1)
                     or (action == "bypass" and (len(args) == 1 or (len(args) == 2 and args[1].casefold() == "stop")))
                     or (action == "ref" and len(args) == 2 and args[1].isascii()
                         and args[1].isdigit() and 0 < int(args[1]) < 2 ** 52)
                     or (action == "run" and len(args) == 2
                         and args[1].upper() in ("G1", "G2", "G3", "G4", "ALL")))
            if not valid or action == "help":
                notice = coroner_text(update.locale, "usage")
            elif action == "acknowledge":
                notice = coroner_text(update.locale, self.service.protection.acknowledge())
                await self.service.save(force=True)
            elif action == "bypass":
                result = await self.service.protection.bypass_limits(user.id, enabled=len(args) == 1)
                notice = coroner_text(update.locale, result) + "\n" + self.service.protection.bypass_status(
                    lambda key, **values: coroner_text(update.locale, key, **values))
            elif action in ("start", "stop", "ref"):
                if action == "start":
                    notice = coroner_text(update.locale, await self.service.start())
                elif action == "stop":
                    await self.service.stop()
                    notice = coroner_text(update.locale, (
                        "error_stopped" if self.service.state.status == "error" else "stopped"
                    ))
                elif chat.type == Chat.PRIVATE:
                    notice = coroner_text(update.locale, "ref_group_only")
                elif await self.service.set_reference(int(args[1]), chat.id):
                    notice = coroner_text(update.locale, "ref_saved", user_id=int(args[1]),
                                          chat_id=self.service.chat_label(chat.id))
                else:
                    notice = coroner_text(update.locale, "ref_failed")
            elif action == "run":
                if self.service.state.status != "running":
                    notice = coroner_text(update.locale, "not_running")
                else:
                    added, existing = await self.service.enqueue_grade(args[1].upper())
                    notice = coroner_text(update.locale, "queued", added=added, existing=existing)
            await self._reply(update, notice)
        except (TelegramError, CoronerInterrupted):
            pass  # The API wrapper has already recorded the actual cause.
        except Exception as error:
            # API calls already recorded a human-readable error. Keep handler
            # exceptions local so Coroner cannot interrupt other moderation.
            self.service._error(chat.id, "command", "worker_error", detail=error)

    @button_click
    async def on_update(
            self, data: CoronerKeyboardData, update: EnrichedUpdate, context: CallbackContext,
    ) -> None:
        query = update.callback_query
        if query.message is None or update.effective_chat is None or update.effective_user is None:
            return
        chat_id = update.effective_chat.id
        try:
            try:
                await self.service.api.call(
                    context.bot.answer_callback_query, callback_query_id=query.id, error_chat_id=chat_id,
                )
            except TelegramError:
                pass  # Expired callbacks can still refresh their status message.
            if not await self.service.authorized(update.effective_user.id, chat_id):
                return
            if update.effective_chat.type != Chat.PRIVATE and not self.service.bot_state.is_chat_moderated(chat_id):
                return
            await self._display(update, edit=True)
        except (TelegramError, CoronerInterrupted):
            pass
        except Exception as error:
            self.service._error(chat_id, "button", "worker_error", detail=error)


    @button_click
    async def on_protection(
            self, data: CoronerProtectionKeyboardData, update: EnrichedUpdate, context: CallbackContext,
    ) -> None:
        if update.callback_query.message is None or update.effective_user is None or update.effective_chat is None:
            return
        chat_id = update.effective_chat.id
        try:
            try:
                await self.service.api.call(context.bot.answer_callback_query,
                                            callback_query_id=update.callback_query.id, error_chat_id=chat_id)
            except TelegramError:
                pass
            if not await self.service.authorized(update.effective_user.id, chat_id):
                return
            if update.effective_chat.type != Chat.PRIVATE and not self.service.bot_state.is_chat_moderated(chat_id):
                return
            action, notice = data.action, ""
            refresh_links = action in ("refresh_review", "refresh_quarantine")
            if refresh_links:
                action = action.removeprefix("refresh_")
            if action == "status":
                await self._display(update, edit=True)
                return
            if action == "new":
                # Retired snapshot buttons simply open the live quarantine.
                action = "review"
            elif action in ("bypass_on", "bypass_off"):
                result = await self.service.protection.bypass_limits(
                    update.effective_user.id, enabled=action == "bypass_on")
                notice = coroner_text(update.locale, result)
                action = "review"
            elif action == "stop":
                await self.service.stop()
                notice = coroner_text(update.locale, (
                    "error_stopped" if self.service.state.status == "error" else "stopped"
                ))
                action = "review"
            elif action == "ack":
                notice = coroner_text(update.locale, self.service.protection.acknowledge())
                action = "review"
            elif action == "approve_all":
                result = await self.service.protection.approve_anomalies(update.effective_user.id)
                notice = coroner_text(update.locale, result)
                action = "review"
            elif action not in ("review", "quarantine", "detectors"):
                notice = coroner_text(update.locale, "review_stale")
                action = "review"
            await self.service.save(force=True)
            await self._protection_display(update, action, data.page, notice,
                                           edit=True, refresh_links=refresh_links)
        except (TelegramError, CoronerInterrupted):
            pass
        except Exception as error:
            self.service._error(chat_id, "protection-button", "worker_error", detail=error)
