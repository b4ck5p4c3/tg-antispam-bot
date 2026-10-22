import os
import tempfile
from pathlib import Path
from threading import RLock


class CoronerStore:
    """Atomic JSON configuration writes; invalid files are never replaced by defaults."""

    def __init__(self, folder: str):
        self.folder = Path(folder)
        self._lock = RLock()

    def load(self, name: str, model_type):
        path = self.folder / name
        if not path.exists():
            value = model_type()
            self.save(name, value.model_dump_json(indent=2))
            return value
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, name: str, snapshot: str) -> None:
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / name
            fd, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=self.folder)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(snapshot)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
