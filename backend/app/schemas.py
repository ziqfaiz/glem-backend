from typing import Any

from pydantic import BaseModel, Field


class TableReplaceRequest(BaseModel):
    """Validate a request that replaces all rows in one dynamically named table."""

    table_name: str = Field(min_length=1, max_length=63)
    fields: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class TableReplaceResponse(BaseModel):
    """Describe whether a table was created and how many rows were written."""

    table_name: str
    created: bool
    rows_written: int
