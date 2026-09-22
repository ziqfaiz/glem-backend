from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TableUpsertRequest(BaseModel):
    """Validate rows to create or upsert into a table in a requested schema."""

    schema_name: str = Field(alias="schema", min_length=1, max_length=63)
    table_name: str = Field(min_length=1, max_length=63)
    primary_key: str | None = Field(default=None, min_length=1, max_length=63)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(populate_by_name=True)


class TableUpsertResponse(BaseModel):
    """Describe the schema, table, and outcome of a batch upsert."""

    schema_name: str = Field(serialization_alias="schema")
    table_name: str
    primary_key: str
    created: bool
    rows_inserted: int
    rows_updated: int

