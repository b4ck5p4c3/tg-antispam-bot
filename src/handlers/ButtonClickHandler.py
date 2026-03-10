import inspect
from typing import Callable, Awaitable, get_type_hints

from telegram.ext import CallbackContext

from src.handlers.BaseHandler import BaseHandler
from src.telegram.EnrichedUpdate import EnrichedUpdate
from src.telegram.KeyboardData import get_keyboard_key_id, parse_keyboard_data, get_keyboard_data_by_key_id, \
    KeyboardData


def button_click(func):
    func._button_click_handler = True
    return func


class ButtonClickHandler(BaseHandler):

    _type_listeners = {}

    def set_listeners(self, *instances):
        for instance in instances:
            for _, method in inspect.getmembers(instance, predicate=inspect.ismethod):
                if not getattr(method, '_button_click_handler', False):
                    continue
                keyboard_data_type = ButtonClickHandler._resolve_keyboard_data_class(method)
                if keyboard_data_type not in self._type_listeners:
                    self._type_listeners[keyboard_data_type] = []
                self._type_listeners[keyboard_data_type].append(method)

    @staticmethod
    def _validate_required_param_type(func_name: str, position_name: str, param_type,
                                      expected_type: type, expected_description: str) -> None:
        if param_type is inspect.Signature.empty:
            raise TypeError(
                f"{position_name} argument of '{func_name}' must be type-annotated as {expected_description}."
            )
        if not isinstance(param_type, type) or not issubclass(param_type, expected_type):
            raise TypeError(
                f"{position_name} argument of '{func_name}' must be {expected_description}, got: {param_type!r}"
            )

    @staticmethod
    def _resolve_param_type(params: list[inspect.Parameter], type_hints: dict[str, object], index: int):
        return type_hints.get(params[index].name, params[index].annotation)

    @staticmethod
    def _resolve_keyboard_data_class(func: Callable[..., Awaitable[None]]) -> type[KeyboardData]:
        signature = inspect.signature(func)
        type_hints = get_type_hints(func)
        params = [param for param in signature.parameters.values() if param.name not in {"self", "cls"}]

        if len(params) < 3:
            raise TypeError(
                f"Handler '{func.__qualname__}' must have at least 3 non-self arguments: "
                f"(KeyboardData, EnrichedUpdate, CallbackContext)."
            )

        first_param_type = ButtonClickHandler._resolve_param_type(params, type_hints, 0)
        second_param_type = ButtonClickHandler._resolve_param_type(params, type_hints, 1)
        third_param_type = ButtonClickHandler._resolve_param_type(params, type_hints, 2)

        ButtonClickHandler._validate_required_param_type(func.__qualname__, "First", first_param_type,
                                      KeyboardData, "a KeyboardData subclass")
        ButtonClickHandler._validate_required_param_type(func.__qualname__, "Second", second_param_type,
                                      EnrichedUpdate, "EnrichedUpdate")
        ButtonClickHandler._validate_required_param_type(func.__qualname__, "Third", third_param_type,
                                      CallbackContext, "CallbackContext")

        return first_param_type

    async def handle_button_click_and_route(self, update: EnrichedUpdate, context: CallbackContext) -> None:
        if update.callback_query is None or update.callback_query.data is None:
            return
        data = update.callback_query.data
        key_id = get_keyboard_key_id(data)
        keyboard_data_type = get_keyboard_data_by_key_id(key_id)
        keyboard_data = parse_keyboard_data(data)
        if keyboard_data_type not in self._type_listeners:
            return
        button_click_handler_funcs = self._type_listeners[keyboard_data_type]
        for button_click_handler_func in button_click_handler_funcs:
            await button_click_handler_func(keyboard_data, update, context)


        
