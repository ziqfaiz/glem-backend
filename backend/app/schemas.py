from typing import Any

from pydantic import BaseModel, Field


class TableReplaceRequest(BaseModel):
    table_name: str = Field(min_length=1, max_length=63)
    fields: list[dict[str, Any]] = Field(min_length=1, max_length=1000)


class TableReplaceResponse(BaseModel):
    table_name: str
    created: bool
    rows_written: int

