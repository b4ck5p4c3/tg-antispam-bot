from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
import inspect

from telegram import Update, Message, User, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler, get_argument_value, admin_command
from src.handlers.ButtonClickHandler import button_click
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.telegram.KeyboardData import KeyboardData, parse_keyboard_data
from src.util.data.BotEvent import BotEvent

DUMB_ACTION_STICKER_ID = "CAACAgIAAxkBAAEQsT5pqwQcNtvIzNeh7_9r0jNl25TxBgACTyQAAm8igUvtKv-k7WtQwDoE"
REPORTS_PER_HOUR_LIMIT = 5

class ReportCommandAction(Enum):
    SUBSCRIBE = ["subscribe", "sub"]
    UNSUBSCRIBE = ["unsubscribe", "unsub"]
    LIST = ["list", "ls"]

@dataclass
class NotificationMessage:
    chat_id: int
    message_id: int

class ReportStatus(Enum):
    PENDING = "PENDING"
    BANNED = "BANNED"
    IGNORED = "IGNORED"

@dataclass
class Report:
    reported_message: Message
    reporter: User
    reported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notified_admins: dict[int, NotificationMessage] = field(default_factory=dict)
    status: ReportStatus = ReportStatus.PENDING
    status_updated_by: User = None

class ReportActionKeyboardData(KeyboardData):
    reported_message_chat_id: int
    reported_message_id: int

class ReportIgnoreKeyboardData(ReportActionKeyboardData):
    key_id: str = "REPORT_IGNORE"

class ReportBanKeyboardData(ReportActionKeyboardData):
    key_id: str = "REPORT_BAN"



class ReportCommandsHandler(BaseHandler):

    chat_report_list: dict[int, list[Report]] = {}

    async def handle_report_command(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        action = get_argument_value(update, 1)
        if action is None:
            await self.handle_spam_report(update, context)
            return

        action_handlers: dict[ReportCommandAction, Callable[[EnrichedUpdate, CallbackContext], Awaitable[None]]] = {
            ReportCommandAction.SUBSCRIBE: self.handle_subscribe_reports,
            ReportCommandAction.UNSUBSCRIBE: self.handle_unsubscribe_reports
        }
        selected_action_handler = None
        for action_handler_command, action_handler in action_handlers.items():
            if action in action_handler_command.value:
                selected_action_handler = action_handler


        if selected_action_handler is None:
            await self.telegram_helper.send_temporary_reply_and_remove_command(context, update.message,
                                                                               update.locale.report_usage)
            return

        await selected_action_handler(update, context)


    @admin_command
    async def handle_subscribe_reports(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        user_id = update.effective_user.id
        if not self.state.subscribe_event(BotEvent.REPORT, user_id):
            await self.telegram_helper.send_temporary_reply_and_remove_command(
                context, update.message, update.locale.report_already_subscribed
            )
            return
        await self.telegram_helper.send_temporary_reply_and_remove_command(
            context, update.message, update.locale.report_subscribed
        )
        self.logger.info(f"User {user_id} subscribed to report events")

    @admin_command
    async def handle_unsubscribe_reports(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        user_id = update.effective_user.id
        if not self.state.unsubscribe_event(BotEvent.REPORT, user_id):
            await self.telegram_helper.send_temporary_reply_and_remove_command(
                context, update.message, update.locale.report_not_subscribed
            )
            return
        await self.telegram_helper.send_temporary_reply_and_remove_command(
            context, update.message, update.locale.report_unsubscribed
        )
        self.logger.info(f"User {user_id} unsubscribed from report events")

    async def handle_spam_report(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        if update.message.reply_to_message is None:
            await self.telegram_helper.send_temporary_reply_and_remove_command(
                context, update.message, update.locale.report_reply_required
            )
            return

        reported_message = update.message.reply_to_message

        if not self.state.is_chat_moderated(reported_message.chat_id):
            await self.telegram_helper.send_temporary_reply_and_remove_command(
                context, update.message, update.locale.chat_not_moderated.format(chat_id=reported_message.chat_id)
            )
            return

        if reported_message.from_user is None or reported_message.from_user.is_bot or reported_message.is_automatic_forward:
            await self.telegram_helper.send_temporary_sticker(context, chat_id=update.effective_chat.id,
                                                              sticker=DUMB_ACTION_STICKER_ID, reply_to_message_id=update.message.id)
            await self.telegram_helper.delete_message_with_delay(context, update.message)
            return

        if update.effective_user.id == reported_message.from_user.id or await self.state.is_admin(reported_message.from_user.id, update.effective_chat.id):
            await self.telegram_helper.send_temporary_reply_and_remove_command(context, update.message,
                                                                               update.locale.durachok)
            return

        if self._get_report(reported_message.message_id, reported_message.chat_id) is not None:
            await self.telegram_helper.send_temporary_reply_and_remove_command(context, update.message,
                                                                               update.locale.report_already_exists)
            return

        reporter = update.effective_user
        if self._has_report_rate_limit_in_last_hour(reporter.id, update.effective_chat.id):
            await self.telegram_helper.send_temporary_reply_and_remove_command(context, update.message,
                                    update.locale.report_rate_limit_hour.format(limit=REPORTS_PER_HOUR_LIMIT))
            return

        report = Report(reported_message=reported_message, reporter=reporter)
        self._get_report_list(update.effective_chat.id).append(report)

        await self.telegram_helper.try_remove_message(context, update.message)
        report_status_message = await self.telegram_helper.send_message(
            context,
            chat_id=update.effective_chat.id,
            text=update.locale.report_reporting_now
        )

        spam_report_subscribers = await self._get_report_subscribers(update.effective_chat.id)
        self.logger.info(f"Sending report to {len(spam_report_subscribers)} subscribers")
        for report_subscriber_id in spam_report_subscribers:
            notification_message = await self._notify_report_subscriber(report_subscriber_id, report, update, context)
            if notification_message is not None:
                report.notified_admins[report_subscriber_id] = notification_message

        notified_admins_count = len(report.notified_admins)
        await context.bot.edit_message_text(
            chat_id=report_status_message.chat_id,
            message_id=report_status_message.message_id,
            text=update.locale.report_reported.format(admins_count=notified_admins_count),
            parse_mode="Markdown",
        )
        await self.telegram_helper.delete_message_with_delay(context, report_status_message)


    async def _get_report_subscribers(self, chat_id: int) -> list[int]:
        spam_report_subscribers = self.state.get_event_subscribers(BotEvent.REPORT)
        for report_subscriber_id in spam_report_subscribers:
            if not await self.state.is_admin(report_subscriber_id, chat_id):
                self.state.unsubscribe_event(BotEvent.REPORT, report_subscriber_id)
                spam_report_subscribers.remove(report_subscriber_id)
        return spam_report_subscribers


    def _get_notification_message(self, report: Report, notified_user_id: int) -> NotificationMessage | None:
        if report.notified_admins is None:
            return None
        if notified_user_id not in report.notified_admins:
            return None
        return report.notified_admins[notified_user_id]

    async def _is_button_click_valid(self, button_data: ReportActionKeyboardData, update: Update) -> bool:
        if not await self.state.is_admin(update.effective_user.id, button_data.reported_message_chat_id):
            return False
        report = self._get_report(button_data.reported_message_id, button_data.reported_message_chat_id)
        if report is None:
            raise ValueError(f"Report for {button_data} was not found")
        if report.status != ReportStatus.PENDING:
            return False
        return True

    @button_click
    async def on_report_ban_button_click(self, button_data: ReportBanKeyboardData, update: EnrichedUpdate, context: CallbackContext):
        if not await self._is_button_click_valid(button_data, update):
            return
        report = self._get_report(button_data.reported_message_id, button_data.reported_message_chat_id)
        report.status = ReportStatus.BANNED
        await self.telegram_helper.try_ban_and_delete_message(context, report.reported_message)
        await self.telegram_helper.audit_log_ban_for_message(report.reported_message, update, context)
        await self._update_notification_message_by_report(report, update, context)



    @button_click
    async def on_report_ignore_button_click(self, button_data: ReportIgnoreKeyboardData, update: EnrichedUpdate, context: CallbackContext):
        if not await self._is_button_click_valid(button_data, update):
            return
        report = self._get_report(button_data.reported_message_id, button_data.reported_message_chat_id)
        report.status = ReportStatus.IGNORED
        await self._update_notification_message_by_report(report, update, context)


    async def _update_notification_message_by_report(self, report: Report, update: EnrichedUpdate, context: CallbackContext):
        for notification_message in report.notified_admins.values():
            if notification_message.chat_id==update.effective_user.id:
                new_notification_message_text = self._get_notification_message_text(report, update)
                await context.bot.edit_message_text(chat_id=notification_message.chat_id,
                                                    message_id=notification_message.message_id,
                                                    text=new_notification_message_text,
                                                    parse_mode="Markdown",
                                                    reply_markup=None)
            else:
                await context.bot.delete_message(notification_message.chat_id, notification_message.message_id)

    def _get_report(self, reported_message_id: int, reported_message_chat_id: int):
        if reported_message_chat_id not in self.chat_report_list:
            return None
        chat_report_list = self.chat_report_list[reported_message_chat_id]
        for report in chat_report_list:
            if report.reported_message.message_id == reported_message_id:
                return report
        return None




    async def _notify_report_subscriber(self, report_subscriber_id: int, report: Report,
                                        update: EnrichedUpdate, context: CallbackContext) -> NotificationMessage | None:
        try:
            report_ban_keyboard_data = ReportBanKeyboardData(
                reported_message_chat_id=report.reported_message.chat_id,
                reported_message_id=report.reported_message.message_id
            )
            report_ignore_keyboard_data = ReportIgnoreKeyboardData(
                reported_message_chat_id=report.reported_message.chat_id,
                reported_message_id=report.reported_message.message_id
            )
            notification_message_text = self._get_notification_message_text(report, update)
            notification_message = await self.telegram_helper.send_message(
                context, report_subscriber_id, notification_message_text,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(text=update.locale.report_ban_button,
                                                 callback_data=report_ban_keyboard_data.model_dump()),
                            InlineKeyboardButton(text=update.locale.report_ignore_button,
                                                 callback_data=report_ignore_keyboard_data.model_dump()),
                        ],
                    ]
                )
            )
            return NotificationMessage(report_subscriber_id, notification_message.message_id)
        except TelegramError as e:
            self.logger.error(f"Failed to notify report subscriber {report_subscriber_id}: {e}")
            return None

    def _get_notification_message_text(self, report: Report, update: EnrichedUpdate):
        reported_message_text = self.telegram_helper.extract_message_text(report.reported_message)
        if reported_message_text is None:
            reported_message_text = update.locale.report_non_text_message_placeholder
        notification_message_text =  update.locale.report_notification_message.format(
            reporter_tag=self.telegram_helper.get_user_tag_md(report.reporter),
            reported_message_link=self.telegram_helper.build_message_link(report.reported_message),
            reported_message_text=reported_message_text)
        if report.status == ReportStatus.BANNED:
            notification_message_text += "\n\n"+update.locale.report_notification_message_user_banned
        elif report.status == ReportStatus.IGNORED:
            notification_message_text += "\n\n"+update.locale.report_notification_message_user_ignored
        return notification_message_text


    def _get_report_list(self, chat_id):
        if chat_id not in self.chat_report_list:
            self.chat_report_list[chat_id] = []
        return self.chat_report_list[chat_id]


    def _has_report_rate_limit_in_last_hour(self, reporter_id: int, chat_id: int) -> bool:
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        reports_last_hour = [report for report in self._get_report_list(chat_id)
                             if report.reporter.id == reporter_id and report.reported_at >= hour_ago]
        return len(reports_last_hour) >= REPORTS_PER_HOUR_LIMIT
