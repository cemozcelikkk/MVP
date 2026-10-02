import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContentReportCreate(BaseModel):
    target_kind: Literal["spot", "photo", "review"] = "spot"
    target_id: uuid.UUID
    reason: Literal[
        "wrong_location", "duplicate", "closed", "incorrect_information", "inappropriate", "other"
    ]
    description: str = Field(min_length=5, max_length=2000)


class ContentReportRead(ContentReportCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    spot_id: uuid.UUID
    state: str
    resolution_note: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class ContentReportResolution(BaseModel):
    action: Literal["resolve", "reject", "hide"]
    note: str = Field(min_length=5, max_length=2000)


class SpotChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    action: str
    before: dict | None
    after: dict
    created_at: datetime
