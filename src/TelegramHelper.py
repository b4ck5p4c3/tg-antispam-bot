import asyncio
from logging import Logger
from typing import Optional

from requests import JSONDecodeError
from telegram.ext import CallbackContext

from src.util.data.BotState import BotState
from telegram import Message, ChatPermissions, File, Chat, User


class TelegramHelper:
    __telegram_api_request_retry_count = 3

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
        user_id = message.from_user.id
        chat_id = message.chat_id
        self.logger.warning(f"Banning user {user_id}")
        await self.__execute_telegram_api_request(context.bot.ban_chat_member, chat_id=chat_id, user_id=user_id)

    async def ban_chat_member(self, context: CallbackContext, chat_id: int, user_id: int) -> None:
        await self.__execute_telegram_api_request(context.bot.ban_chat_member, chat_id=chat_id, user_id=user_id)

    async def add_message_reaction(self, context: CallbackContext, message: Message, reaction: str) -> None:
        await self.__execute_telegram_api_request(context.bot.set_message_reaction, chat_id=message.chat_id,
                                                  message_id=message.id,
                                                  reaction=reaction)

    async def send_message(self, context: CallbackContext, chat_id: int, text: str = None, **kwargs) -> Message:
        return await self.__execute_telegram_api_request(context.bot.send_message, chat_id=chat_id, text=text,
                                                         parse_mode="Markdown", **kwargs)

    async def send_temporary_message(self, context: CallbackContext, chat_id: int, text: str,
                                     remove_in_seconds: int = 30) -> None:
        message = await self.send_message(context, chat_id=chat_id, text=text)
        await self.delete_message_with_delay(context, message, remove_in_seconds)

    async def send_temporary_sticker(self, context: CallbackContext, chat_id: int, sticker: str,
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
        await self.delete_message_with_delay(context, message, remove_in_seconds)

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

    async def audit_log(self, context: CallbackContext, source_message: Message, message: str) -> None:
        audit_log_chat_id = self.state.get_audit_log_chat_id()
        self.logger.info(f"Sending audit log message `{message}` to chat {audit_log_chat_id}")
        if audit_log_chat_id is None:
            await self.send_message(context, chat_id=source_message.chat_id, text=self.__get_audit_log_message(message))
            return
        await self.send_message(context, chat_id=audit_log_chat_id, text=self.__get_audit_log_message(message))

    @staticmethod
    def get_user_tag_md(user: User) -> str:
        if user.username is not None:
            return f"@{user.username}"
        return f"[{user.first_name}](tg://user?id={user.id})"

    @staticmethod
    def extract_message_text(message: Message) -> Optional[str]:
        if message.text is not None:
            return message.text
        if message.caption is not None:
            return message.caption
        return None

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
