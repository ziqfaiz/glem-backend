from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OutputItem(BaseModel):
    uuid: UUID
    sender_id: str | None = None
    sender_name: str | None = None
    trx_date: datetime | None = None
    receiver_id: str | None = None
    receiver_name: str | None = None
    type: str | None = None
    dc: str | None = None
    amount: int | None = None
    status: str | None = None
    created_dt: date


class OutputUpsertRequest(BaseModel):
    items: list[OutputItem] = Field(alias="$items", min_length=1, max_length=1000)

    model_config = ConfigDict(populate_by_name=True)


class OutputUpsertResponse(BaseModel):
    upserted: int

