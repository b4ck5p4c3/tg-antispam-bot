import asyncio
from logging import Logger
from typing import Optional

from requests import JSONDecodeError
from telegram import Chat, ChatPermissions, File, Message, PhotoSize, User
from telegram.ext import CallbackContext

from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.util.DevelopmentMode import get_development_delay_seconds, is_development_mode
from src.util.data.BotState import BotState


class TelegramHelper:
    __telegram_api_request_retry_count = 3
    __development_unban_delay_seconds = 5

    def __init__(self, logger: Logger, state: BotState):
        self.logger = logger
        self.state = state

    async def try_remove_message(self, context: CallbackContext, message: Message) -> None:
        try:
            await self.__execute_telegram_api_request(context.bot.delete_message, chat_id=message.chat_id,
                                                      message_id=message.message_id)
        except Exception as e:
            self.logger.warning(f"Failed to remove message {message.message_id}: {e}")

    async def delete_message_with_delay(self, context: CallbackContext, message: Message,
                                        delay_seconds: int = 30) -> None:
        self.logger.debug(f"Deleting message {message.message_id} with delay {delay_seconds}")
        context.job_queue.run_once(lambda ctx: self.try_remove_message(context, message), delay_seconds)

    async def ban_message_author(self, context: CallbackContext, message: Message) -> None:
        chat_id = message.chat_id
        sender_chat = self.extract_message_sender_chat(message)
        if sender_chat is not None:
            self.logger.warning(f"Banning sender chat {sender_chat.id}")
            await self.ban_chat_sender_chat(context, chat_id=chat_id, sender_chat_id=sender_chat.id)
            return

        user = self.extract_message_user(message)
        if user is None:
            raise ValueError(f"Cannot determine message author for message {message.message_id}")
        self.logger.warning(f"Banning user {user.id}")
        await self.ban_chat_member(context, chat_id=chat_id, user_id=user.id)

    async def try_ban_and_delete_message(self, context: CallbackContext, message: Message) -> None:
        await self.try_remove_message(context, message)

        await self.ban_message_author(context, message)

    async def audit_log_ban_for_message(self, message: Message, update: EnrichedUpdate, context: CallbackContext,
                                        message_quote_max_len: int = 200) -> None:
        message_text = self.extract_message_text(message)
        if message_text is None:
            message_text = update.locale.report_non_text_message_placeholder
        truncated_message = message_text[:message_quote_max_len]
        sender_chat = self.extract_message_sender_chat(message)
        if sender_chat is not None:
            audit_log_message = update.locale.audit_log_channel_banned_by_reply.format(
                banned_channel_name=self.get_chat_display_name(sender_chat),
                banned_channel_id=sender_chat.id,
                banned_by=update.effective_user,
                message=truncated_message,
                chat=message.chat
            )
        else:
            banned_user = self.extract_message_user(message)
            if banned_user is None:
                raise ValueError(f"Cannot determine message author for audit log for message {message.message_id}")
            audit_log_message = update.locale.audit_log_user_banned_by_reply.format(
                banned_user=banned_user,
                banned_by=update.effective_user,
                message=truncated_message,
                chat=message.chat
            )
        message_photo = self.extract_message_photo(message)

        await self.audit_log(context, update.message, audit_log_message, photo=message_photo)


    async def ban_chat_member(self, context: CallbackContext, chat_id: int, user_id: int) -> None:
        await self.__execute_telegram_api_request(context.bot.ban_chat_member, chat_id=chat_id, user_id=user_id)
        self.state.untrust(user_id)
        if is_development_mode():
            unban_delay_seconds = get_development_delay_seconds(
                "DEVELOPMENT_UNBAN_DELAY_SECONDS",
                self.__development_unban_delay_seconds,
            )
            self.logger.warning(
                "Development mode: scheduling unban of user %s in chat %s after %s seconds",
                user_id,
                chat_id,
                unban_delay_seconds,
            )
            context.job_queue.run_once(
                lambda job_context: self.unban_chat_member(job_context, chat_id, user_id),
                unban_delay_seconds,
            )

    async def unban_chat_member(self, context: CallbackContext, chat_id: int, user_id: int) -> None:
        await self.__execute_telegram_api_request(
            context.bot.unban_chat_member,
            chat_id=chat_id,
            user_id=user_id,
            only_if_banned=True,
        )
        self.logger.info("Unbanned user %s in chat %s", user_id, chat_id)

    async def ban_chat_sender_chat(self, context: CallbackContext, chat_id: int, sender_chat_id: int) -> None:
        await self.__execute_telegram_api_request(context.bot.ban_chat_sender_chat, chat_id=chat_id,
                                                  sender_chat_id=sender_chat_id)

    async def add_message_reaction(self, context: CallbackContext, message: Message, reaction: str) -> None:
        await self.__execute_telegram_api_request(context.bot.set_message_reaction, chat_id=message.chat_id,
                                                  message_id=message.id,
                                                  reaction=reaction)

    async def send_message(self, context: CallbackContext, chat_id: int, text: str = None, **kwargs) -> Message:
        return await self.__execute_telegram_api_request(context.bot.send_message, chat_id=chat_id, text=text,
                                                         parse_mode="Markdown", **kwargs)

    async def send_photo(self, context: CallbackContext, chat_id: int, photo: str | PhotoSize,
                         caption: str | None = None, **kwargs) -> Message:
        return await self.__execute_telegram_api_request(context.bot.send_photo, chat_id=chat_id, photo=photo,
                                                         caption=caption, parse_mode="Markdown", **kwargs)

    async def send_temporary_message(self, context: CallbackContext, chat_id: int, text: str,
                                     remove_in_seconds: int = 30) -> None:
        message = await self.send_message(context, chat_id=chat_id, text=text)
        await self.delete_message_with_delay(context, message, remove_in_seconds)

    async def send_sticker(self, context: CallbackContext, chat_id: int, sticker: str,
                                     remove_in_seconds: int = 30,
                                     reply_to_message_id: Optional[int] = None) -> None:
        try:
            send_sticker_kwargs = {
                "chat_id": chat_id,
                "sticker": sticker
            }
            if reply_to_message_id is not None:
                send_sticker_kwargs["reply_to_message_id"] = reply_to_message_id
            message = await self.__execute_telegram_api_request(context.bot.send_sticker, **send_sticker_kwargs)
        except Exception as e:
            self.logger.warning(f"Failed to send sticker to chat {chat_id}: {e}")
            return
        if message is None:
            self.logger.warning(f"Failed to send sticker to chat {chat_id}: empty Telegram API response")
            return

    async def send_temporary_reply_and_remove_command(self, context: CallbackContext, command_message: Message,
                                                      text: str, remove_in_seconds: int = 30) -> None:
        await self.delete_message_with_delay(context, command_message)
        await self.send_temporary_message(context, chat_id=command_message.chat_id, text=text,
                                          remove_in_seconds=remove_in_seconds)

    async def restrict_chat_member(self, context: CallbackContext, chat_id: int, user_id: int,
                                   permissions: ChatPermissions) -> None:
        await self.__execute_telegram_api_request(context.bot.restrict_chat_member, chat_id=chat_id, user_id=user_id,
                                                  permissions=permissions)

    async def get_file(self, context: CallbackContext, **kwargs) -> 'File':
        return await self.__execute_telegram_api_request(context.bot.get_file, **kwargs)

    async def get_chat(self, context: CallbackContext, chat_id: int) -> 'Chat':
        return await self.__execute_telegram_api_request(context.bot.get_chat, chat_id=chat_id)

    async def audit_log(self, context: CallbackContext, source_message: Message, message: str,
                        photo: str | PhotoSize | None = None) -> None:
        audit_log_chat_id = self.state.get_audit_log_chat_id()
        self.logger.info(f"Sending audit log message `{message}` to chat {audit_log_chat_id}")
        target_chat_id = source_message.chat_id if audit_log_chat_id is None else audit_log_chat_id
        audit_log_message = self.__get_audit_log_message(message)
        if photo is not None:
            await self.send_photo(context, chat_id=target_chat_id, photo=photo, caption=audit_log_message,
                                  has_spoiler=True)
            return
        if audit_log_chat_id is None:
            await self.send_message(context, chat_id=source_message.chat_id, text=audit_log_message)
            return
        await self.send_message(context, chat_id=audit_log_chat_id, text=audit_log_message)


    def get_user_hyperlink(self, user_id: int):
        cached_user = self.state.get_cached_user(user_id)
        if cached_user is None:
            return f"[Undefined](tg://user?id={user_id})"
        return f"[{cached_user.first_name}](tg://user?id={cached_user.id})"


    @staticmethod
    def extract_message_text(message: Message) -> Optional[str]:
        if message.text is not None:
            return message.text
        if message.caption is not None:
            return message.caption
        return None

    @staticmethod
    def extract_message_user(message: Message) -> Optional[User]:
        if message.sender_chat is not None:
            return None
        return message.from_user

    @staticmethod
    def extract_message_sender_chat(message: Message) -> Optional[Chat]:
        if message.sender_chat is None or message.sender_chat.id == message.chat_id:
            return None
        return message.sender_chat

    @staticmethod
    def is_message_from_anonymous_admin(message: Message) -> bool:
        return message.sender_chat is not None and message.sender_chat.id == message.chat_id

    @staticmethod
    def extract_message_photo(message: Message) -> Optional[PhotoSize]:
        if message.photo is None or len(message.photo) == 0:
            return None
        return message.photo[-1]

    @staticmethod
    def get_chat_display_name(chat: Chat) -> str:
        if chat.title is not None:
            return chat.title
        if chat.first_name is not None and chat.last_name is not None:
            return f"{chat.first_name} {chat.last_name}"
        if chat.first_name is not None:
            return chat.first_name
        if chat.username is not None:
            return chat.username
        return str(chat.id)

    @staticmethod
    def build_message_link(message: Message) -> str:
        if message.chat.username is not None:
            return f"https://t.me/{message.chat.username}/{message.message_id}"
        chat_id = str(message.chat_id)
        if chat_id.startswith("-100"):
            chat_id = chat_id[4:]
        return f"https://t.me/c/{chat_id}/{message.message_id}"


    @staticmethod
    def __get_audit_log_message(message: str):
        return f"[#auditlog] {message}"

    async def __execute_telegram_api_request(self, func, *args, **kwargs):
        for _ in range(self.__telegram_api_request_retry_count):
            try:
                return await func(*args, **kwargs)
            except JSONDecodeError as e:
                self.logger.warning(f"Telegram API request failed: {e}")
                await asyncio.sleep(1)
        self.logger.error(
            f"Failed to execute Telegram API request after {self.__telegram_api_request_retry_count} retries for {func.__name__}")
