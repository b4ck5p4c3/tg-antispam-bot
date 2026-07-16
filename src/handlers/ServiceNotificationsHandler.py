import asyncio
from datetime import datetime
from html import escape

from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import CallbackContext

from src.handlers.EventSubscriptionCommandsHandler import EventSubscriptionCommandsHandler
from src.locale.Locale import Locale
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.data.BotEvent import BotEvent
from src.util.data.BotState import BotState


class ServiceNotificationsHandler(EventSubscriptionCommandsHandler):
    _subscription_event = BotEvent.SERVICE
    _subscription_locale_prefix = "service"

    def __init__(self, state: BotState, default_locale: Locale):
        super().__init__(state)
        self.default_locale = default_locale

    async def handle_service_command(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        await self.handle_subscription_command(update, context)

    async def notify_openai_unavailable(self, context: CallbackContext, error: str) -> dict[int, int]:
        notification_text = self.default_locale.openai_service_unavailable.format(error=error)
        subscribers = self.state.get_event_subscribers(BotEvent.SERVICE)
        self.logger.info(f"Sending OpenAI incident notification to {len(subscribers)} subscribers")

        notification_results = await asyncio.gather(
            *(self._send_incident_notification(context, subscriber_id, notification_text)
              for subscriber_id in subscribers)
        )
        return {
            subscriber_id: message_id
            for subscriber_id, message_id in notification_results
            if message_id is not None
        }

    async def notify_openai_recovered(
            self,
            context: CallbackContext,
            error: str,
            resolved_at: datetime,
            notifications: dict[int, int],
    ) -> None:
        unavailable_text = self.default_locale.openai_service_unavailable.format(error=error)
        recovered_text = self.default_locale.openai_service_recovered.format(
            resolved_at=resolved_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        notification_text = f"<s>{escape(unavailable_text)}</s>\n\n{escape(recovered_text)}"

        await asyncio.gather(
            *(self._edit_incident_notification(context, chat_id, message_id, notification_text)
              for chat_id, message_id in notifications.items())
        )

    async def _send_incident_notification(
            self,
            context: CallbackContext,
            subscriber_id: int,
            notification_text: str,
    ) -> tuple[int, int | None]:
        try:
            message = await context.bot.send_message(
                chat_id=subscriber_id,
                text=escape(notification_text),
                parse_mode=ParseMode.HTML,
            )
            return subscriber_id, message.message_id
        except TelegramError as error:
            self.logger.error(f"Failed to notify service subscriber {subscriber_id}: {error}")
            return subscriber_id, None

    async def _edit_incident_notification(
            self,
            context: CallbackContext,
            chat_id: int,
            message_id: int,
            notification_text: str,
    ) -> None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=notification_text,
                parse_mode=ParseMode.HTML,
            )
        except TelegramError as error:
            self.logger.error(f"Failed to resolve service notification for subscriber {chat_id}: {error}")
