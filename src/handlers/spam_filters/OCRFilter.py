import asyncio
import io

import pytesseract
from PIL import Image, UnidentifiedImageError
from pytesseract import TesseractNotFoundError, TesseractError
from telegram import PhotoSize
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
            file_bytes = await self.__get_image_bytes(context, photo)
            if file_bytes is not None:
                text = self.__recognize_image(file_bytes)
                recognized_photos.append(PhotoSizeWithRecognition(photo, text))
        update.set_recognized_photos(tuple(recognized_photos))
        return False

    async def __get_image_bytes(self, context: CallbackContext, photo: PhotoSize) -> bytes | None:
        for attempt in range(1, self._DOWNLOAD_ATTEMPTS + 1):
            try:
                file = await self.telegram_helper.get_file(context, file_id=photo.file_id)
                return bytes(await file.download_as_bytearray())
            except Exception as error:
                if attempt == self._DOWNLOAD_ATTEMPTS:
                    self.logger.exception(
                        "Failed to download photo %s after %s attempts; continuing spam analysis without OCR",
                        photo.file_unique_id,
                        self._DOWNLOAD_ATTEMPTS,
                    )
                    return None
                self.logger.warning(
                    "Failed to download photo %s on attempt %s/%s, retrying: %s: %s",
                    photo.file_unique_id,
                    attempt,
                    self._DOWNLOAD_ATTEMPTS,
                    type(error).__name__,
                    error,
                )
                await asyncio.sleep(self._DOWNLOAD_RETRY_DELAY_SECONDS)
        return None

    def __recognize_image(self, image_bytes: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            return pytesseract.image_to_string(image, lang=self.tesseract_lang)
        except (TesseractNotFoundError, TesseractError, UnidentifiedImageError, OSError):
            self.logger.exception("Failed to recognize downloaded photo; continuing spam analysis without OCR")
            return ""
