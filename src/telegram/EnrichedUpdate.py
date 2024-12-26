from click import Tuple
from telegram import Update

from src.locale.Locale import Locale
from src.locale.LocaleFactory import LocaleFactory
from src.telegram.PhotoSizeWithRecognition import PhotoSizeWithRecognition


class EnrichedUpdate(Update):
    def __init__(self, update: Update, locale: Locale):
        super().__init__(
            update.update_id,
            message=update.message,
            edited_message=update.edited_message,
            channel_post=update.channel_post,
            edited_channel_post=update.edited_channel_post,
            inline_query=update.inline_query,
            chosen_inline_result=update.chosen_inline_result,
            callback_query=update.callback_query,
            shipping_query=update.shipping_query,
            pre_checkout_query=update.pre_checkout_query,
            poll=update.poll,
            poll_answer=update.poll_answer,
            my_chat_member=update.my_chat_member,
            chat_member=update.chat_member,
            chat_join_request=update.chat_join_request,
            chat_boost=update.chat_boost,
            removed_chat_boost=update.removed_chat_boost,
            message_reaction=update.message_reaction,
            message_reaction_count=update.message_reaction_count,
            business_connection=update.business_connection,
            business_message=update.business_message,
            edited_business_message=update.edited_business_message,
            deleted_business_messages=update.deleted_business_messages,
            purchased_paid_media=update.purchased_paid_media,
        )
        self._locale = locale
        self._recognized_photos = None

    @staticmethod
    def from_update(update: Update, locale_factory: LocaleFactory) -> 'EnrichedUpdate':
        if update.effective_user is not None:
            locale = locale_factory.get_locale_for_user(update.effective_user)
        else:
            locale = locale_factory.get_default_locale()
        return EnrichedUpdate(update, locale)

    @property
    def locale(self):
        return self._locale

    @property
    def recognized_photos(self) -> tuple[PhotoSizeWithRecognition, ...]:
        return self._recognized_photos

    def set_recognized_photos(self, recognized_photos: tuple[PhotoSizeWithRecognition, ...]):
        self._recognized_photos = recognized_photos