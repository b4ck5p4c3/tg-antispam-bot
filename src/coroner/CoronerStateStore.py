import fcntl
import json
import sqlite3
from pathlib import Path
from threading import RLock

from src.coroner.CoronerModels import CoronerState


class CoronerStateStore:
    """One writer, transactional entity updates, and concurrent read-only access."""

    FILE_NAME = "coroner_state.sqlite3"
    SCHEMA_VERSION = 2
    APPLICATION_ID = 0x43524E52
    _STATE_MAPS = ("users", "queue")
    _PROTECTION_MAPS = ("quarantine", "rejected_until", "reasons", "approvals", "notifications", "populations")
    _LISTS = {"removals": "operation_id", "checks": "id", "reservations": "id"}
    _EVENT_LISTS = ("cancelled_candidates", "activity_conflicts")

    def __init__(self, folder: str | Path, filename: str = FILE_NAME):
        self.path = Path(folder) / filename
        self._lock = RLock()
        self._writer_lock = None
        self._connection = None
        self._saved_records = {}
        self._data_version = None

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    @classmethod
    def _records(cls, snapshot):
        state = dict(snapshot)
        protection = dict(state.pop("protection"))
        records = {}

        def add(collection, key, value):
            identity = collection, str(key)
            if identity in records:
                raise ValueError(f"Duplicate Coroner record: {identity}")
            records[identity] = cls._json(value)

        for collection in cls._STATE_MAPS:
            for key, value in state.pop(collection).items():
                add(collection, key, value)
        for collection, id_field in cls._LISTS.items():
            owner = state if collection == "removals" else protection
            for item in owner.pop(collection):
                add(collection, item[id_field], item)
        for collection in cls._PROTECTION_MAPS:
            for key, value in protection.pop(collection).items():
                add(collection, key, value)
        for day, observation in protection.pop("days").items():
            add("days", day, observation["coverage_seconds"])
            for user_id, grade in observation["candidates"].items():
                add("daily_candidates", f"{day}:{user_id}", grade)
        for metric, observations in protection.pop("metrics").items():
            add("metric_series", metric, None)
            for observation in observations:
                add("metrics", cls._json([metric, observation["id"]]), observation)
        for collection in cls._EVENT_LISTS:
            occurrences = {}
            for event in protection.pop(collection):
                value = cls._json(event)
                occurrence = occurrences.get(value, 0)
                occurrences[value] = occurrence + 1
                add(collection, cls._json([event, occurrence]), event)
        for key, value in state.items():
            add("state", key, value)
        for key, value in protection.items():
            add("protection", key, value)
        return records

    @classmethod
    def _decode(cls, rows):
        state = {key: {} for key in cls._STATE_MAPS}
        state.update(removals=[])
        protection = {key: {} for key in (*cls._PROTECTION_MAPS, "days", "metrics")}
        protection.update({key: [] for key in ("checks", "reservations", *cls._EVENT_LISTS)})
        state["protection"] = protection
        for collection, key, encoded in rows:
            value = json.loads(encoded)
            if collection == "state":
                if key in state or key not in CoronerState.model_fields:
                    raise ValueError(f"Invalid Coroner state field: {key}")
                state[key] = value
            elif collection == "protection":
                if key in protection or key not in CoronerState.model_fields["protection"].annotation.model_fields:
                    raise ValueError(f"Invalid Coroner protection field: {key}")
                protection[key] = value
            elif collection in cls._STATE_MAPS:
                state[collection][key] = value
            elif collection in cls._LISTS:
                owner = state if collection == "removals" else protection
                if value[cls._LISTS[collection]] != key:
                    raise ValueError(f"Invalid Coroner record identity: {collection}")
                owner[collection].append(value)
            elif collection in cls._PROTECTION_MAPS:
                protection[collection][key] = value
            elif collection == "days":
                protection["days"].setdefault(key, {"candidates": {}})["coverage_seconds"] = value
            elif collection == "daily_candidates":
                day, user_id = key.split(":")
                protection["days"].setdefault(day, {"coverage_seconds": 0, "candidates": {}})["candidates"][user_id] = value
            elif collection == "metric_series":
                protection["metrics"].setdefault(key, [])
            elif collection == "metrics":
                metric, observation_id = json.loads(key)
                if value["id"] != observation_id:
                    raise ValueError("Invalid Coroner metric identity")
                protection["metrics"].setdefault(metric, []).append(value)
            elif collection in cls._EVENT_LISTS:
                protection[collection].append(value)
            else:
                raise ValueError(f"Unknown Coroner collection: {collection}")
        if "version" not in state or "status" not in state:
            raise ValueError("Incomplete Coroner database")
        return CoronerState.model_validate(state)

    @classmethod
    def _validate_database(cls, connection):
        if (connection.execute("PRAGMA application_id").fetchone()[0] != cls.APPLICATION_ID
                or connection.execute("PRAGMA user_version").fetchone()[0] != cls.SCHEMA_VERSION):
            raise ValueError("Not a supported Coroner SQLite database")
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("Coroner SQLite integrity check failed")

    @classmethod
    def read(cls, path: str | Path):
        """Read a consistent committed state without obtaining the writer lock."""
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            connection.execute("BEGIN")
            cls._validate_database(connection)
            return cls._decode(connection.execute("SELECT collection, key, value FROM records ORDER BY rowid"))
        finally:
            connection.close()

    def load(self, initial: CoronerState | None = None):
        with self._lock:
            if self._connection is not None:
                raise RuntimeError("Coroner database is already open")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._writer_lock = open(str(self.path) + ".lock", "a+b")
            try:
                fcntl.flock(self._writer_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                exists = self.path.exists()
                if initial is not None and exists:
                    raise FileExistsError(self.path)
                initial_records = self._records((initial or CoronerState()).model_dump(mode="json")) if not exists else None
                connection = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
                self._connection = connection
                if exists:
                    self._validate_database(connection)
                if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                    raise RuntimeError("Could not enable Coroner SQLite WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("PRAGMA wal_autocheckpoint=1000")
                if not exists:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        connection.execute("CREATE TABLE records (collection TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (collection, key))")
                        connection.executemany("INSERT INTO records VALUES (?, ?, ?)",
                                               [(collection, key, value) for (collection, key), value in initial_records.items()])
                        connection.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
                        connection.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
                        connection.execute("COMMIT")
                    except BaseException:
                        connection.execute("ROLLBACK")
                        raise
                self._data_version = connection.execute("PRAGMA data_version").fetchone()[0]
                rows = connection.execute("SELECT collection, key, value FROM records ORDER BY rowid").fetchall()
                state = self._decode(rows)
                if connection.execute("PRAGMA data_version").fetchone()[0] != self._data_version:
                    raise RuntimeError("Coroner database changed during startup")
                self._saved_records = {(collection, key): value for collection, key, value in rows}
                return state
            except BaseException:
                self.close()
                raise

    def save(self, snapshot):
        records = self._records(snapshot)
        with self._lock:
            connection = self._connection
            if connection is None:
                raise RuntimeError("Coroner database is closed")
            if connection.execute("PRAGMA data_version").fetchone()[0] != self._data_version:
                raise RuntimeError("Coroner database was modified by another writer")
            removed = self._saved_records.keys() - records.keys()
            changed = [(collection, key, value) for (collection, key), value in records.items()
                       if self._saved_records.get((collection, key)) != value]
            if not removed and not changed:
                return
            connection.execute("BEGIN IMMEDIATE")
            try:
                if connection.execute("PRAGMA data_version").fetchone()[0] != self._data_version:
                    raise RuntimeError("Coroner database was modified by another writer")
                connection.executemany("DELETE FROM records WHERE collection=? AND key=?", list(removed))
                connection.executemany("INSERT INTO records VALUES (?, ?, ?) ON CONFLICT(collection, key) DO UPDATE SET value=excluded.value", changed)
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            self._saved_records = records

    def close(self):
        with self._lock:
            try:
                if self._connection is not None:
                    self._connection.close()
                    self._connection = None
            finally:
                if self._writer_lock is not None:
                    self._writer_lock.close()
                    self._writer_lock = None
