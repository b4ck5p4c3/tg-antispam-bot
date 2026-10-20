from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.coroner.CoronerProtectionModels import ProtectionConfig, ProtectionState


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["G1", "G2", "G3", "G4"]
    max_age_seconds: int | None = Field(default=None, gt=0, strict=True)
    check_interval_seconds: int = Field(gt=0, strict=True)


class CoronerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(default=False, strict=True)
    max_requests_per_minute: int = Field(default=450, gt=0, strict=True)
    reference_check_every: int = Field(default=10, gt=0, strict=True)
    reference_user_id: int | None = Field(default=None, gt=0, strict=True)
    reference_chat_id: int | None = Field(default=None, lt=0, strict=True)
    retry_delay_seconds: int = Field(default=60, gt=0, strict=True)
    protection: ProtectionConfig = Field(default_factory=ProtectionConfig)
    grades: list[Grade] = Field(default_factory=lambda: [
        Grade(name="G1", max_age_seconds=86400, check_interval_seconds=1800),
        Grade(name="G2", max_age_seconds=604800, check_interval_seconds=7200),
        Grade(name="G3", max_age_seconds=2592000, check_interval_seconds=86400),
        Grade(name="G4", check_interval_seconds=259200),
    ])

    @model_validator(mode="after")
    def validate_schedule(self):
        if [grade.name for grade in self.grades] != ["G1", "G2", "G3", "G4"]:
            raise ValueError("grades must contain G1, G2, G3, G4 in order")
        limits = [grade.max_age_seconds for grade in self.grades]
        if any(value is None for value in limits[:3]) or limits[3] is not None:
            raise ValueError("only G4 must have an unlimited age")
        if not limits[0] < limits[1] < limits[2]:
            raise ValueError("grade age limits must be increasing")
        if (self.reference_user_id is None) != (self.reference_chat_id is None):
            raise ValueError("reference_user_id and reference_chat_id must be set together")
        return self

    def grade_for(self, since: float, now: float) -> Grade:
        age = max(0, now - since)
        return next(grade for grade in self.grades
                    if grade.max_age_seconds is None or age < grade.max_age_seconds)


class Participant(BaseModel):
    first_seen_at: float
    joined_at: float | None = None
    active: bool = True
    status: str = "member"
    last_event_at: float = 0
    last_departure_at: float = 0
    last_update_id: int = -1
    generation: int = 0
    last_successful_check: float | None = None
    next_check_at: float = 0

    @property
    def since(self) -> float:
        return self.joined_at if self.joined_at is not None else self.first_seen_at


class CheckJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    chat_id: int
    user_id: int
    generation: int
    enqueued_at: float
    not_before: float = 0
    source: Literal["scheduled", "manual"] = "scheduled"
    attempts: int = 0
    stage: Literal["check", "removing"] = "check"

    @property
    def key(self) -> str:
        return f"{self.chat_id}:{self.user_id}"


class TrackedUser(BaseModel):
    since: float
    first_chat_id: int
    last_alive_at: float | None = None


class Removal(BaseModel):
    operation_id: str
    chat_id: int
    user_id: int
    grade: Literal["G1", "G2", "G3", "G4"]
    removed_at: float


class CoronerState(BaseModel):
    version: Literal[1] = 1
    status: Literal["stopped", "running", "error"] = "stopped"
    participants: dict[int, dict[int, Participant]] = Field(default_factory=dict)
    users: dict[int, TrackedUser] = Field(default_factory=dict)
    excluded_user_ids: set[int] = Field(default_factory=set)
    queue: dict[str, CheckJob] = Field(default_factory=dict)
    removals: list[Removal] = Field(default_factory=list)
    protection: ProtectionState = Field(default_factory=ProtectionState)
    moderated_chats: list[int] = Field(default_factory=list)
    checks_since_reference: int = 0
    last_reference_at: float | None = None
    last_reference_alive: bool | None = None
