from telegram import User

from src.locale.Locale import Locale


class LocaleName:
    ENGLISH = 'en'


class LocaleFactory:
    __DEFAULT_LOCALE = LocaleName.ENGLISH

    def __init__(self, locale_folder_path: str):
        self.locale_folder_path = locale_folder_path

    def get_locale_for_user(self, user: User) -> Locale:
        locale_name = user.language_code
        locale_file_value = self._get_locale_file_value(locale_name)
        return Locale.model_validate_json(locale_file_value)

    def get_locale(self, locale_name: str) -> Locale:
        locale_file_value = self._get_locale_file_value(locale_name)
        return Locale.model_validate_json(locale_file_value)

    def _get_locale_file_value(self, locale_name: str) -> str:
        if locale_name not in LocaleName.__dict__.values():
            locale_name = self.__DEFAULT_LOCALE
        with open(f"{self.locale_folder_path}/en.json", 'r') as file: # TODO: Fix
            return file.read()

    def get_default_locale(self) -> Locale:
        return self.get_locale(self.__DEFAULT_LOCALE)