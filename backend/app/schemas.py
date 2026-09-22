from typing import Any

from pydantic import BaseModel, Field


class TableUpsertRequest(BaseModel):
    """Validate rows to create or upsert into a dynamically named table."""

    table_name: str = Field(min_length=1, max_length=63)
    primary_key: str | None = Field(default=None, min_length=1, max_length=63)
    fields: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class TableUpsertResponse(BaseModel):
    """Describe whether a table was created and how many rows were upserted."""

    table_name: str
    primary_key: str
    created: bool
    rows_upserted: int
