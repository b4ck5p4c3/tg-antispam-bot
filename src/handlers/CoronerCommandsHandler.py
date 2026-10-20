from html import escape
import time

from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.coroner.CoronerApi import CoronerInterrupted
from src.coroner.CoronerMessages import coroner_text
from src.coroner.CoronerService import CoronerService
from src.coroner.CoronerProtectionView import CoronerProtectionKeyboardData, CoronerProtectionView
from src.coroner.CoronerProtectionModels import SafetySignal
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

    async def _protection_display(self, update, action, request_id="-", page=0, user_id=0,
                                  notice="", *, edit=False):
        if action == "detectors":
            try:
                await self.service.protection.populations()
            except CoronerInterrupted:
                raise
            except Exception:
                pass
        view = CoronerProtectionView(self.service, update.locale)
        text, keyboard, parse_mode = view.render(action, request_id, update.effective_user.id, page, user_id)
        if notice:
            text = (escape(notice) if parse_mode == "HTML" else notice) + "\n\n" + text
        params = dict(chat_id=update.effective_chat.id, text=text, reply_markup=keyboard,
                      parse_mode=parse_mode, error_chat_id=update.effective_chat.id)
        if edit:
            message = await self.service.api.call(
                self.service.bot.edit_message_text,
                message_id=update.callback_query.message.message_id, **params,
            )
            if message is None:
                message = update.callback_query.message
        else:
            message = await self.service.api.call(self.service.bot.send_message, **params)
        if isinstance(message, Message):
            corrected = view.replace_missing_profile_links(text, message)
            if corrected != text:
                params["text"] = corrected
                await self.service.api.call(
                    self.service.bot.edit_message_text,
                    message_id=message.message_id, **params,
                )

    async def _reply(self, update, text):
        chat_id = update.effective_chat.id
        await self.service.api.call(
            self.service.bot.send_message, chat_id=chat_id, text=text,
            parse_mode=None, error_chat_id=chat_id,
        )

    async def _display(self, update, *, edit=False):
        chat_id = update.effective_chat.id
        text = await self.service.status_text(update.locale)
        kwargs = dict(chat_id=chat_id, text=text, parse_mode=None,
                      reply_markup=self._keyboard(update.locale), error_chat_id=chat_id)
        if edit:
            await self.service.api.call(
                self.service.bot.edit_message_text,
                message_id=update.callback_query.message.message_id, **kwargs,
            )
        else:
            await self.service.api.call(self.service.bot.send_message, **kwargs)

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
                await self._protection_display(update, action)
                return
            valid = ((action in ("help", "start", "stop", "acknowledge") and len(args) == 1)
                     or (action == "ref" and len(args) == 2 and args[1].isascii()
                         and args[1].isdigit() and 0 < int(args[1]) < 2 ** 52)
                     or (action == "run" and len(args) == 2
                         and args[1].upper() in ("G1", "G2", "G3", "G4", "ALL")))
            if not valid or action == "help":
                notice = coroner_text(update.locale, "usage")
            elif action == "acknowledge":
                notice = coroner_text(update.locale, self.service.protection.acknowledge())
                await self.service.save(force=True)
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
                    notice = coroner_text(update.locale, "ref_saved", user_id=int(args[1]), chat_id=chat.id)
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
            action, request_id, notice = data.action, data.request_id, ""
            if action == "status":
                await self._display(update, edit=True)
                return
            if action == "new":
                if not self.service.state.protection.blocked:
                    self.service.protection.trip(SafetySignal(key="manual-review", kind="manual", at=time.time()))
                    request_id = self.service.state.protection.current_request_id
                else:
                    request_id = self.service.protection.new_request().id
                action = "review"
            elif action == "ack":
                notice = coroner_text(update.locale, self.service.protection.acknowledge())
                action = "review"
            elif action in ("select", "qselect", "approve", "approve_all", "reject", "recheck"):
                review_action = "select" if action == "qselect" else action
                result = self.service.protection.review(
                    request_id, update.effective_user.id, review_action, data.user_id,
                )
                notice = coroner_text(update.locale, result)
                action = {"qselect": "quarantine", "select": "accounts"}.get(action, "review")
            elif action not in ("review", "accounts", "quarantine", "detectors", "detail"):
                return
            await self.service.save(force=True)
            await self._protection_display(update, action, request_id, data.page, data.user_id, notice, edit=True)
        except (TelegramError, CoronerInterrupted):
            pass
        except Exception as error:
            self.service._error(chat_id, "protection-button", "worker_error", detail=error)
