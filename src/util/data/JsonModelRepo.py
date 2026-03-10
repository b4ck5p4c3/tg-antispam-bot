import os
from threading import RLock
from typing import TypeVar, Type

from pydantic import BaseModel

from src.util.data.ModelRepo import ModelRepo

T = TypeVar('T', bound=BaseModel)


class JsonModelRepo(ModelRepo[T]):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self._lock = RLock()

    def save(self, model: T) -> None:
        with self._lock:
            with open(self.file_path, 'w') as f:
                f.write(model.model_dump_json(indent=4))

    def load(self, model_class: Type[T], default: T) -> T:
        with self._lock:
            if not os.path.exists(self.file_path):
                self.save(default)
                return default
            with open(self.file_path) as f:
                return model_class.model_validate_json(f.read())
