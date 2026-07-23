import asyncio
import hashlib
import io
import logging
import re
import time
import traceback
import urllib.parse

import pytesseract
from PIL import Image, UnidentifiedImageError
from pytesseract import TesseractNotFoundError, TesseractError
from telegram import File, PhotoSize
from telegram.ext import CallbackContext

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.telegram.PhotoSizeWithRecognition import PhotoSizeWithRecognition
from src.util.data.BotState import BotState

"""Not a real spam filter, enriches the update attached images with OCR text"""


class OCRFilter(SpamFilter):
    _DOWNLOAD_ATTEMPTS = 3
    _DOWNLOAD_RETRY_DELAY_SECONDS = 1

    def __init__(self, state: BotState, tesseract_executable_path: str, tesseract_lang: str,
                 next_filter: SpamFilter = None):
        super().__init__(state, next_filter)
        pytesseract.pytesseract.tesseract_cmd = (
            tesseract_executable_path
            if tesseract_executable_path
            else pytesseract.pytesseract.tesseract_cmd
        )
        self.tesseract_lang = tesseract_lang

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        recognized_photos = []
        if update.message.photo:
            photo = update.message.photo[-1]
            trace_id = f"[chat_id={update.message.chat_id} message_id={update.message.id}]"
            self.logger.debug(
                "%s OCR photo selected: variants=%s selected_unique_id=%s "
                "selected_file_id=%s width=%s height=%s file_size=%s",
                trace_id,
                len(update.message.photo),
                photo.file_unique_id,
                self.__describe_identifier(photo.file_id),
                photo.width,
                photo.height,
                photo.file_size,
            )
            file_bytes = await self.__get_image_bytes(context, photo, trace_id)
            if file_bytes is not None:
                text = self.__recognize_image(file_bytes)
                recognized_photos.append(PhotoSizeWithRecognition(photo, text))
        update.set_recognized_photos(tuple(recognized_photos))
        return False

    async def __get_image_bytes(
            self,
            context: CallbackContext,
            photo: PhotoSize,
            trace_id: str,
    ) -> bytes | None:
        bot = context.bot
        token = bot.token
        request = bot.request
        self.logger.debug(
            "%s OCR download configuration: api_url=%s get_file_url=%s file_base_url=%s "
            "local_mode=%s request_type=%s default_read_timeout=%s",
            trace_id,
            self.__sanitize(bot.base_url, token),
            self.__sanitize(f"{bot.base_url}/getFile", token),
            self.__sanitize(bot.base_file_url, token),
            bot.local_mode,
            type(request).__name__,
            request.read_timeout,
        )

        for attempt in range(1, self._DOWNLOAD_ATTEMPTS + 1):
            phase = "get_file"
            telegram_file: File | None = None
            started_at = time.monotonic()
            self.logger.debug(
                "%s OCR download attempt %s/%s started: phase=get_file method=POST url=%s "
                "params={file_id=%s} timeouts=library_defaults",
                trace_id,
                attempt,
                self._DOWNLOAD_ATTEMPTS,
                self.__sanitize(f"{bot.base_url}/getFile", token),
                self.__describe_identifier(photo.file_id),
            )
            try:
                telegram_file = await self.telegram_helper.get_file(context, file_id=photo.file_id)
                phase = "download"
                download_url = self.__encoded_url(telegram_file.file_path)
                self.logger.debug(
                    "%s OCR get_file succeeded on attempt %s/%s: returned_unique_id=%s "
                    "returned_file_id=%s file_size=%s file_path=%s",
                    trace_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    telegram_file.file_unique_id,
                    self.__describe_identifier(telegram_file.file_id),
                    telegram_file.file_size,
                    self.__sanitize(download_url, token),
                )
                self.logger.debug(
                    "%s OCR download HTTP request on attempt %s/%s: method=GET url=%s "
                    "params={} timeouts=library_defaults request_type=%s",
                    trace_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    self.__sanitize(download_url, token),
                    type(telegram_file.get_bot().request).__name__,
                )
                image_bytes = bytes(await telegram_file.download_as_bytearray())
                self.logger.debug(
                    "%s OCR download attempt %s/%s succeeded: bytes=%s elapsed_ms=%s",
                    trace_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    len(image_bytes),
                    round((time.monotonic() - started_at) * 1000),
                )
                return image_bytes
            except Exception as error:
                elapsed_ms = round((time.monotonic() - started_at) * 1000)
                error_details = self.__format_exception(error, token)
                self.logger.warning(
                    "%s OCR download attempt %s/%s failed: phase=%s elapsed_ms=%s "
                    "error_type=%s error_repr=%s error_args=%s cause=%s context=%s",
                    trace_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    phase,
                    elapsed_ms,
                    type(error).__name__,
                    self.__sanitize(repr(error), token),
                    self.__sanitize(repr(error.args), token),
                    self.__sanitize(repr(error.__cause__), token),
                    self.__sanitize(repr(error.__context__), token),
                )
                self.logger.debug(
                    "%s OCR download attempt %s/%s sanitized traceback:\n%s",
                    trace_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    error_details,
                )
                await self.__log_raw_response(
                    context=context,
                    photo=photo,
                    telegram_file=telegram_file,
                    phase=phase,
                    attempt=attempt,
                    trace_id=trace_id,
                )
                if attempt == self._DOWNLOAD_ATTEMPTS:
                    self.logger.error(
                        "%s Failed to download photo %s after %s attempts; "
                        "continuing spam analysis without OCR. Last error: %s",
                        trace_id,
                        photo.file_unique_id,
                        self._DOWNLOAD_ATTEMPTS,
                        self.__sanitize(repr(error), token),
                    )
                    return None
                self.logger.warning(
                    "%s Failed to download photo %s on attempt %s/%s, retrying in %ss",
                    trace_id,
                    photo.file_unique_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    self._DOWNLOAD_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(self._DOWNLOAD_RETRY_DELAY_SECONDS)
        return None

    async def __log_raw_response(
            self,
            context: CallbackContext,
            photo: PhotoSize,
            telegram_file: File | None,
            phase: str,
            attempt: int,
            trace_id: str,
    ) -> None:
        """Repeat a failed request at the transport level to expose HTTP status and body."""
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        bot = context.bot
        token = bot.token
        request = bot.request
        method = "GET"
        if phase == "download" and telegram_file is not None:
            url = self.__encoded_url(telegram_file.file_path)
            if not url.startswith(("http://", "https://")):
                self.logger.debug(
                    "%s OCR raw diagnostic probe skipped on attempt %s/%s: "
                    "file path is local path=%s",
                    trace_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    self.__sanitize(url, token),
                )
                return
            request = telegram_file.get_bot().request
        else:
            query = urllib.parse.urlencode({"file_id": photo.file_id})
            url = f"{bot.base_url}/getFile?{query}"

        self.logger.debug(
            "%s OCR raw diagnostic probe on attempt %s/%s: original_phase=%s "
            "method=%s url=%s request_type=%s",
            trace_id,
            attempt,
            self._DOWNLOAD_ATTEMPTS,
            phase,
            method,
            self.__sanitize(url, token, redact_file_id=True),
            type(request).__name__,
        )
        try:
            status_code, payload = await request.do_request(url=url, method=method)
            payload_preview = payload[:4096].decode("utf-8", errors="replace")
            self.logger.debug(
                "%s OCR raw diagnostic response on attempt %s/%s: original_phase=%s "
                "status=%s payload_bytes=%s payload_truncated=%s payload=%r",
                trace_id,
                attempt,
                self._DOWNLOAD_ATTEMPTS,
                phase,
                status_code,
                len(payload),
                len(payload) > 4096,
                self.__sanitize(payload_preview, token),
            )
        except Exception as probe_error:
            self.logger.debug(
                "%s OCR raw diagnostic probe failed on attempt %s/%s: "
                "error_type=%s error_repr=%s traceback=\n%s",
                trace_id,
                attempt,
                self._DOWNLOAD_ATTEMPTS,
                type(probe_error).__name__,
                self.__sanitize(repr(probe_error), token),
                self.__format_exception(probe_error, token),
            )

    @staticmethod
    def __describe_identifier(value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
        return f"sha256:{digest}/length:{len(value)}"

    @staticmethod
    def __encoded_url(file_path: str | None) -> str:
        if not file_path:
            return "<missing>"
        split_url = urllib.parse.urlsplit(str(file_path))
        return urllib.parse.urlunsplit(
            urllib.parse.SplitResult(
                split_url.scheme,
                split_url.netloc,
                urllib.parse.quote(split_url.path),
                split_url.query,
                split_url.fragment,
            )
        )

    @classmethod
    def __format_exception(cls, error: Exception, token: str) -> str:
        formatted = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        return cls.__sanitize(formatted, token)

    @staticmethod
    def __sanitize(value: str, token: str, redact_file_id: bool = False) -> str:
        sanitized = str(value)
        for token_variant in (token, urllib.parse.quote(token, safe="")):
            if token_variant:
                sanitized = sanitized.replace(token_variant, "<BOT_TOKEN>")
        sanitized = re.sub(
            r"(?i)(?:bot)?\d{6,}:[A-Za-z0-9_-]{20,}",
            "<BOT_TOKEN>",
            sanitized,
        )
        if redact_file_id:
            sanitized = re.sub(r"([?&]file_id=)[^&#]+", r"\1<FILE_ID>", sanitized)
        return sanitized

    def __recognize_image(self, image_bytes: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            return pytesseract.image_to_string(image, lang=self.tesseract_lang)
        except (TesseractNotFoundError, TesseractError, UnidentifiedImageError, OSError):
            self.logger.exception("Failed to recognize downloaded photo; continuing spam analysis without OCR")
            return ""
