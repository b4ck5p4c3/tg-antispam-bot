from typing import TypeVar, Generic, Type

from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)
class ModelRepo(Generic[T]):
    def save(self, model: T) -> None:
        raise NotImplementedError()

    def load(self, model_class: Type[T], default: T) -> T:
        raise NotImplementedError()
