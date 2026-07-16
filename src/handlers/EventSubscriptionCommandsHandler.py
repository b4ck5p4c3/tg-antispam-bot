from enum import Enum

from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler, admin_command, get_argument_value
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.data.BotEvent import BotEvent


class SubscriptionCommandAction(Enum):
    SUBSCRIBE = ["subscribe", "sub"]
    UNSUBSCRIBE = ["unsubscribe", "unsub"]
    LIST = ["list", "ls"]


class EventSubscriptionCommandsHandler(BaseHandler):
    _subscription_event: BotEvent
    _subscription_locale_prefix: str

    async def handle_subscription_command(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        action = get_argument_value(update, 1)
        action_handlers = {
            SubscriptionCommandAction.SUBSCRIBE: self._handle_subscribe,
            SubscriptionCommandAction.UNSUBSCRIBE: self._handle_unsubscribe,
            SubscriptionCommandAction.LIST: self._handle_list_subscribers,
        }

        for command_action, handler in action_handlers.items():
            if action in command_action.value:
                await handler(update, context)
                return

        await self.telegram_helper.send_temporary_reply_and_remove_command(
            context,
            update.message,
            self._get_locale_text(update, "usage"),
        )

    @admin_command
    async def _handle_subscribe(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        user_id = update.effective_user.id
        if not self.state.subscribe_event(self._subscription_event, user_id):
            await self._send_subscription_reply(update, context, "already_subscribed")
            return

        await self._send_subscription_reply(update, context, "subscribed")
        self.logger.info(f"User {user_id} subscribed to {self._subscription_event.value} events")

    @admin_command
    async def _handle_unsubscribe(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        user_id = update.effective_user.id
        if not self.state.unsubscribe_event(self._subscription_event, user_id):
            await self._send_subscription_reply(update, context, "not_subscribed")
            return

        await self._send_subscription_reply(update, context, "unsubscribed")
        self.logger.info(f"User {user_id} unsubscribed from {self._subscription_event.value} events")

    async def _send_subscription_reply(
            self,
            update: EnrichedUpdate,
            context: CallbackContext,
            locale_suffix: str,
    ) -> None:
        await self.telegram_helper.send_message(
            context,
            chat_id=update.effective_chat.id,
            text=self._get_locale_text(update, locale_suffix),
            reply_to_message_id=update.message.id,
        )

    async def _handle_list_subscribers(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        subscribers = await self._get_event_subscribers(update.effective_chat.id)
        if len(subscribers) == 0:
            await self.telegram_helper.send_message(
                context,
                chat_id=update.effective_chat.id,
                text=self._get_locale_text(update, "list_empty"),
                reply_to_message_id=update.message.id,
            )
            return

        subscribers_hyperlinks = [self.telegram_helper.get_user_hyperlink(user_id) for user_id in subscribers]
        subscribers_list = "\n".join(
            f"{index}. {user_hyperlink}"
            for index, user_hyperlink in enumerate(subscribers_hyperlinks, start=1)
        )
        await self.telegram_helper.send_message(
            context,
            chat_id=update.effective_chat.id,
            text=self._get_locale_text(update, "list_subscribers").format(subscribers=subscribers_list),
            reply_to_message_id=update.message.id,
        )

    async def _get_event_subscribers(self, chat_id: int) -> list[int]:
        return self.state.get_event_subscribers(self._subscription_event)

    def _get_locale_text(self, update: EnrichedUpdate, suffix: str) -> str:
        return getattr(update.locale, f"{self._subscription_locale_prefix}_{suffix}")
