from typing import Literal
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from src.coroner.CoronerProtectionModels import ProtectionConfig, ProtectionState


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["G1", "G2", "G3", "G4"]
    max_age_seconds: int | None = Field(default=None, gt=0, strict=True)
    max_check_interval_seconds: int = Field(
        gt=0, strict=True,
        validation_alias=AliasChoices("max_check_interval_seconds", "check_interval_seconds"),
    )


class CoronerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = Field(default=False, strict=True)
    max_requests_per_minute: int = Field(default=450, gt=0, strict=True)
    min_check_inverval_precent: float = Field(default=10, gt=0, le=100, strict=True, allow_inf_nan=False)
    reference_check_every: int = Field(default=10, gt=0, strict=True)
    reference_user_id: int | None = Field(default=None, gt=0, strict=True)
    reference_chat_id: int | None = Field(default=None, lt=0, strict=True)
    retry_delay_seconds: int = Field(default=60, gt=0, strict=True)
    invalid_response_retries: int = Field(default=1, ge=0, le=5, strict=True)
    invalid_response_retry_delay_seconds: float = Field(default=1, ge=0, allow_inf_nan=False)
    protection: ProtectionConfig = Field(default_factory=ProtectionConfig)
    grades: list[Grade] = Field(default_factory=lambda: [
        Grade(name="G1", max_age_seconds=86400, max_check_interval_seconds=1800),
        Grade(name="G2", max_age_seconds=604800, max_check_interval_seconds=7200),
        Grade(name="G3", max_age_seconds=2592000, max_check_interval_seconds=86400),
        Grade(name="G4", max_check_interval_seconds=259200),
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


class CheckJob(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    chat_id: int | None = None
    user_id: int
    generation: int
    enqueued_at: float
    not_before: float = 0
    source: Literal["scheduled", "manual"] = "scheduled"
    attempts: int = 0

    @property
    def key(self) -> str:
        return str(self.user_id)


class TrackedUser(BaseModel):
    chat_ids: list[int] = Field(default_factory=list)
    generation: int = 0
    last_successful_check: float | None = None
    next_check_at: float = 0
    since: float
    first_chat_id: int
    last_alive_at: float | None = None
    last_grade: Literal["G1", "G2", "G3", "G4"] | None = None


class Removal(BaseModel):
    operation_id: str
    chat_id: int
    user_id: int
    grade: Literal["G1", "G2", "G3", "G4"]
    removed_at: float


class CoronerState(BaseModel):
    version: Literal[2] = 2
    status: Literal["stopped", "running", "error"] = "stopped"
    users: dict[int, TrackedUser] = Field(default_factory=dict)
    queue: dict[str, CheckJob] = Field(default_factory=dict)
    removals: list[Removal] = Field(default_factory=list)
    protection: ProtectionState = Field(default_factory=ProtectionState)
    moderated_chats: list[int] = Field(default_factory=list)
    checks_since_reference: int = 0
    last_reference_at: float | None = None
    last_reference_alive: bool | None = None
