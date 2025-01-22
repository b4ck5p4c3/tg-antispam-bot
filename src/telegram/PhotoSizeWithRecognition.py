from telegram import PhotoSize


class PhotoSizeWithRecognition:

    def __init__(self, image: PhotoSize, ocr_text: str):
        self.image = image
        self.ocr_text = ocr_text
