from math import isfinite
from datetime import timezone
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


def calendar_timezone(name):
    return timezone.utc if name == "UTC" else ZoneInfo(name)


class ProtectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RateRule(ProtectionModel):
    window_seconds: int = Field(default=1800, gt=0, strict=True)
    minimum_users: int = Field(default=20, gt=0, strict=True)
    minimum_matches: int = Field(default=1, gt=0, strict=True)
    threshold_percent: float = Field(default=80, gt=0, le=100)


class RemovalLimit(ProtectionModel):
    name: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    window_seconds: int = Field(gt=0, strict=True)
    chat_percent: float = Field(gt=0, le=100)
    global_percent: float = Field(gt=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def discard_absolute_limits(cls, values):
        if isinstance(values, dict):
            return {key: value for key, value in values.items() if key not in ("chat_count", "global_count")}
        return values


class ProtectionConfig(ProtectionModel):
    quarantine_seconds: int = Field(default=3600, ge=0, strict=True)
    recheck_seconds: int = Field(default=300, gt=0, strict=True)
    removal_limit_bypass_seconds: int = Field(default=7200, gt=0, strict=True)
    rejection_cooldown_seconds: int = Field(default=86400, gt=0, strict=True)
    candidate_history_days: int = Field(default=7, gt=0, le=90, strict=True)
    candidate_coefficients: dict[str, float] = Field(default_factory=lambda: dict.fromkeys(
        ("G1", "G2", "G3", "G4"), 3.0,
    ))
    candidate_minimum_users: dict[str, int] = Field(default_factory=lambda: dict.fromkeys(
        ("G1", "G2", "G3", "G4"), 5,
    ))
    day_timezone: str = "UTC"
    minimum_day_coverage_percent: float = Field(default=100, gt=0, le=100)
    maximum_collection_gap_seconds: int = Field(default=30, gt=0, strict=True)
    false_results: RateRule = Field(default_factory=RateRule)
    recent_alive_seconds: int = Field(default=86400, gt=0, strict=True)
    alive_transitions: RateRule = Field(default_factory=lambda: RateRule(
        minimum_matches=5, threshold_percent=50,
    ))
    profile_inconsistencies: RateRule = Field(default_factory=lambda: RateRule(
        minimum_matches=3, threshold_percent=20,
    ))
    activity_minimum_users: int = Field(default=1, gt=0, strict=True)
    activity_window_seconds: int = Field(default=1800, gt=0, strict=True)
    metric_sample_seconds: int = Field(default=300, gt=0, strict=True)
    metric_history_days: int = Field(default=7, gt=0, le=90, strict=True)
    removal_statistics_days: int = Field(default=7, gt=0, le=365, strict=True)
    notification_interval_seconds: int = Field(default=300, gt=0, strict=True)
    member_count_cache_seconds: int = Field(default=60, gt=0, strict=True)
    account_links_per_page: int = Field(default=100, gt=0, le=100, strict=True)
    account_links_per_row: int = Field(default=3, gt=0, le=8, strict=True)
    account_link_retry_seconds: int = Field(default=300, gt=0, strict=True)
    detector_page_size: int = Field(default=3, gt=0, le=3, strict=True)
    reservation_retention_days: int = Field(default=30, gt=0, le=365, strict=True)
    removal_limits: list[RemovalLimit] = Field(default_factory=lambda: [
        RemovalLimit(name="short", window_seconds=600, chat_percent=5, global_percent=5),
        RemovalLimit(name="daily", window_seconds=86400, chat_percent=10, global_percent=10),
    ])

    @model_validator(mode="before")
    @classmethod
    def discard_removed_settings(cls, values):
        # Retire settings for removed detectors, account cards and review snapshots.
        if isinstance(values, dict):
            return {key: value for key, value in values.items() if key not in (
                "api_errors", "review_page_size", "approval_seconds", "resolved_request_retention_days",
            )}
        return values

    @model_validator(mode="after")
    def validate_rules(self):
        grades = {"G1", "G2", "G3", "G4"}
        if set(self.candidate_coefficients) != grades or set(self.candidate_minimum_users) != grades:
            raise ValueError("candidate settings must contain exactly G1, G2, G3, G4")
        if any(not isfinite(value) or value <= 0 for value in self.candidate_coefficients.values()):
            raise ValueError("candidate coefficients must be positive and finite")
        if any(type(value) is not int or value <= 0 for value in self.candidate_minimum_users.values()):
            raise ValueError("candidate minimum counts must be positive integers")
        if not self.removal_limits or len({item.name for item in self.removal_limits}) != len(self.removal_limits):
            raise ValueError("removal limits must be nonempty and have unique names")
        calendar_timezone(self.day_timezone)
        return self


class QuarantineCandidate(BaseModel):
    user_id: int
    grade: str
    detected_at: float
    ready_at: float
    targets: list[int] = Field(default_factory=list)
    generation: int = 0


class CheckObservation(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: int
    chat_id: int
    at: float
    result: Literal["alive", "deleted", "unknown"]
    recently_alive: bool = False
    primary: bool = True


class DayObservation(BaseModel):
    coverage_seconds: float = 0
    candidates: dict[int, str] = Field(default_factory=dict)


class MetricRange(BaseModel):
    count: int = 0
    total: float = 0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value):
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(self.minimum, value)
        self.maximum = value if self.maximum is None else max(self.maximum, value)


class MetricObservation(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    at: float
    samples: int
    matches: int
    value: float
    window_seconds: int = 0
    percentage: bool = False
    attempts: int = 0
    false_attempts: int = 0
    sample_range: MetricRange = Field(default_factory=MetricRange)
    match_range: MetricRange = Field(default_factory=MetricRange)
    value_range: MetricRange = Field(default_factory=MetricRange)
    attempts_range: MetricRange = Field(default_factory=MetricRange)
    false_attempts_range: MetricRange = Field(default_factory=MetricRange)
    weighted_samples: int = 0
    weighted_matches: int = 0

    def observe(self, samples, matches, value, at, attempts=0, false_attempts=0):
        self.at, self.samples, self.matches, self.value = at, samples, matches, value
        self.attempts, self.false_attempts = attempts, false_attempts
        for record, item in ((self.sample_range, samples), (self.match_range, matches),
                             (self.attempts_range, attempts), (self.false_attempts_range, false_attempts)):
            record.add(item)
        if samples or not self.percentage:
            self.value_range.add(value)
        if samples:
            self.weighted_samples += samples
            self.weighted_matches += matches


class SafetySignal(BaseModel):
    key: str
    kind: str
    at: float
    value: float = 0
    threshold: float = 0
    chat_id: int | None = None
    grade: str | None = None
    user_id: int | None = None
    unit: Literal["percent"] | None = None
    rule: str = ""


class AnomalyApproval(BaseModel):
    user_id: int
    at: float
    rule: str = ""


class RemovalReservation(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: int
    chat_id: int
    at: float
    chat_population: int
    global_population: int
    dry_run: bool
    state: Literal["pending", "completed", "uncertain", "released"] = "pending"


class ProtectionState(BaseModel):
    day_timezone: str | None = None
    quarantine: dict[int, QuarantineCandidate] = Field(default_factory=dict)
    checks: list[CheckObservation] = Field(default_factory=list)
    days: dict[str, DayObservation] = Field(default_factory=dict)
    metrics: dict[str, list[MetricObservation]] = Field(default_factory=dict)
    rejected_until: dict[int, float] = Field(default_factory=dict)
    cancelled_candidates: list[tuple[float, int]] = Field(default_factory=list)
    activity_conflicts: list[tuple[float, int]] = Field(default_factory=list)
    removal_limit_bypass_until: float = Field(default=0, ge=0, allow_inf_nan=False)
    removal_limit_bypass_by: int | None = Field(default=None, gt=0, strict=True)
    reasons: dict[str, SafetySignal] = Field(default_factory=dict)
    approvals: dict[str, AnomalyApproval] = Field(default_factory=dict)
    notifications: dict[int, int] = Field(default_factory=dict)
    notification_at: float = 0
    notification_version: int = 0
    reservations: list[RemovalReservation] = Field(default_factory=list)
    populations: dict[int, int] = Field(default_factory=dict)
    populations_at: float = 0
    populations_chats: list[int] = Field(default_factory=list)
    reservations_discarded_until: float = 0

    @model_validator(mode="before")
    @classmethod
    def migrate_review_state(cls, values):
        if not isinstance(values, dict):
            return values
        values = dict(values)
        # Reuse the existing subscriber messages, without expanding old account approvals.
        requests = values.get("requests", {})
        request = requests.get(values.get("current_request_id"), {})
        if "notifications" not in values:
            values["notifications"] = request.get("notifications", {})
        if values.get("blocked") and not values.get("reasons"):
            values["reasons"] = {"manual-review": dict(key="manual-review", kind="manual", at=0)}
        return values
