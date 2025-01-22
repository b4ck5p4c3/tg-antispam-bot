import io

import pytesseract
from PIL import Image
from pytesseract import TesseractNotFoundError
from telegram import PhotoSize
from telegram.ext import CallbackContext

from src.handlers.spam_filters.SpamFilter import SpamFilter
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.telegram.PhotoSizeWithRecognition import PhotoSizeWithRecognition
from src.util.config.Config import Config

"""Not a real spam filter, enriches the update attached images with OCR text"""


class OCRFilter(SpamFilter):
    def __init__(self, config: Config, tesseract_executable_path: str, tesseract_lang: str,
                 next_filter: SpamFilter = None):
        super().__init__(config, next_filter)
        pytesseract.pytesseract.tesseract_cmd = tesseract_executable_path if tesseract_executable_path else pytesseract.pytesseract.tesseract_cmd
        self.tesseract_lang = tesseract_lang

    async def _is_spam(self, update: EnrichedUpdate, context: CallbackContext) -> bool:
        recognized_photos = []
        for photo in update.message.photo:
            file_bytes = await self.__get_image_bytes(context, photo)
            text = self.__recognize_image(file_bytes)
            recognized_photos.append(PhotoSizeWithRecognition(photo, text))
        update.set_recognized_photos(tuple(recognized_photos))
        return False

    async def __get_image_bytes(self, context: CallbackContext, photo: PhotoSize) -> bytes:
        file = await self.telegram_helper.get_file(context, file_id=photo)
        return await file.download_as_bytearray()

    def __recognize_image(self, image_bytes: bytes) -> str:
        image = Image.open(io.BytesIO(image_bytes))
        try:
            return pytesseract.image_to_string(image, lang=self.tesseract_lang)
        except TesseractNotFoundError:
            self.logger.error("Tesseract not found, please install Tesseract for OCR support")
            return ""
