import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def is_development_mode() -> bool:
    return os.getenv("DEVELOPMENT_MODE", "").strip().lower() in _TRUE_VALUES


def get_development_delay_seconds(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed_value = int(value)
    except ValueError:
        return default
    return parsed_value if parsed_value > 0 else default
