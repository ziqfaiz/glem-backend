from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TableCreateRequest(BaseModel):
    """Validate source column metadata used to define a new destination table."""

    schema_name: str = Field(alias="schema", min_length=1, max_length=63)
    table_name: str = Field(min_length=1, max_length=63)
    primary_key: list[str] = Field(min_length=1, max_length=63)
    columns: list["SourceColumn"] = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(populate_by_name=True)


class TableUpsertRequest(BaseModel):
    """Validate rows that will be inserted or updated in an existing table."""

    schema_name: str = Field(alias="schema", min_length=1, max_length=63)
    table_name: str = Field(min_length=1, max_length=63)
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(populate_by_name=True)


class SourceColumn(BaseModel):
    """The source-system metadata needed to create one PostgreSQL column."""

    column_name: str = Field(min_length=1, max_length=63)
    ordinal_position: int = Field(ge=1)
    data_type: str = Field(min_length=1, max_length=100)
    is_nullable: str = Field(min_length=2, max_length=3)


class TableCreateResponse(BaseModel):
    """Describe a successfully created table."""

    schema_name: str = Field(serialization_alias="schema")
    table_name: str
    primary_key: list[str]
    created: bool


class TableUpsertResponse(BaseModel):
    """Describe the schema, table, and outcome of a batch upsert."""

    schema_name: str = Field(serialization_alias="schema")
    table_name: str
    primary_key: list[str]
    rows_inserted: int
    rows_updated: int
