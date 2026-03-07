from typing import Any, Optional, TypeVar, ClassVar
from urllib.parse import unquote, quote

from pydantic import BaseModel, model_validator, model_serializer

T = TypeVar("T", bound="KeyboardData")


def all_subclasses(cls: type[T]) -> list[type[T]]:
    out: list[type[T]] = []
    for sub in cls.__subclasses__():
        out.append(sub)
        out.extend(all_subclasses(sub))
    return out


class KeyboardData(BaseModel):
    key_id: str
    SEP: ClassVar[str] = ":"

    @model_validator(mode="before")
    @classmethod
    def parse_from_string(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value

        field_names = list(cls.model_fields.keys())
        parts = value.split(cls.SEP)

        if len(parts) != len(field_names):
            raise ValueError(
                f"{cls.__name__} expects {len(field_names)} values, got {len(parts)}"
            )

        return {name: unquote(part) for name, part in zip(field_names, parts)}

    @model_serializer(mode="plain")
    def dump_to_string(self) -> str:
        field_names = list(self.__class__.model_fields.keys())
        values = [quote(str(getattr(self, name)), safe="") for name in field_names]
        return self.SEP.join(values)


def get_keyboard_data_by_key_id(key_id: str) -> type[KeyboardData]:
    all_keyboards = all_subclasses(KeyboardData)
    keyboard_by_id: dict[str, type[KeyboardData]] = {}
    for keyboard in all_keyboards:
        key_id_field = keyboard.model_fields.get("key_id")
        field_default = None if key_id_field is None else key_id_field.default
        if isinstance(field_default, str):
            keyboard_by_id[field_default] = keyboard
    return keyboard_by_id[key_id]


def get_keyboard_key_id(data: str) -> Optional[str]:
    if data is None:
        return None
    return data.split(KeyboardData.SEP, 1)[0]


def parse_keyboard_data(data: str) -> KeyboardData:
    key_id = get_keyboard_key_id(data)
    if key_id is None:
        raise ValueError("Keyboard key_id is empty")
    keyboard_data_class = get_keyboard_data_by_key_id(key_id)
    return keyboard_data_class.model_validate(data)
