import re
from datetime import date, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    MetaData,
    Table,
    Text,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .schemas import TableUpsertRequest, TableUpsertResponse


SCHEMA_NAME = "public"
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


app = FastAPI(title=get_settings().app_name, version="3.0.0")


def validate_identifier(value: str, label: str) -> str:
    """Reject unsafe SQL table and column identifiers supplied by a request."""
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{label} must start with a lowercase letter and contain only "
                "lowercase letters, numbers, and underscores."
            ),
        )
    return value


def infer_column_type(values: list[Any]):
    """Infer one SQLAlchemy column type from all non-null values for one field."""
    non_null_values = [value for value in values if value is not None]
    if not non_null_values:
        return Text

    value_types = {type(value) for value in non_null_values}
    if value_types == {bool}:
        return Boolean
    if value_types <= {int}:
        return BigInteger
    if value_types <= {int, float}:
        return Float
    if value_types == {UUID}:
        return PG_UUID(as_uuid=True)
    if value_types == {datetime}:
        return DateTime(timezone=True)
    if value_types == {date}:
        return Date
    if all(isinstance(value, (dict, list)) for value in non_null_values):
        return JSONB
    return Text


def table_from_fields(
    table_name: str,
    primary_key: str,
    fields: list[dict[str, Any]],
) -> Table:
    """Build a table definition and mark the requested incoming field as its key."""
    column_names = {column_name for row in fields for column_name in row}
    if not column_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fields must contain at least one column.",
        )
    if primary_key not in column_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="primary_key must be present in fields.",
        )
    if any(primary_key not in row or row[primary_key] is None for row in fields):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Every row must contain a non-null primary_key value.",
        )

    columns = []
    for column_name in sorted(column_names):
        validate_identifier(column_name, "Field name")
        values = [row.get(column_name) for row in fields]
        columns.append(
            Column(
                column_name,
                infer_column_type(values),
                primary_key=column_name == primary_key,
                nullable=column_name != primary_key,
            )
        )

    return Table(table_name, MetaData(schema=SCHEMA_NAME), *columns)


def normalized_rows(
    fields: list[dict[str, Any]], column_names: set[str]
) -> list[dict[str, Any]]:
    """Give every insert row the same column set, using NULL for missing values."""
    return [
        {column_name: row.get(column_name) for column_name in column_names}
        for row in fields
    ]


def deduplicate_rows_by_primary_key(
    fields: list[dict[str, Any]], primary_key: str
) -> list[dict[str, Any]]:
    """Keep the final row for a repeated key, preventing one batch conflict error."""
    if any(isinstance(row[primary_key], (dict, list)) for row in fields):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="primary_key values must be scalar values, not objects or arrays.",
        )
    return list({row[primary_key]: row for row in fields}.values())


def resolve_existing_primary_key(table: Table, requested_key: str | None) -> str:
    """Use a supplied key or discover the single primary key on an existing table."""
    existing_keys = list(table.primary_key.columns.keys())
    if len(existing_keys) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Existing table must have exactly one primary-key column.",
        )

    existing_key = existing_keys[0]
    if requested_key is not None and requested_key != existing_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Existing table primary key is {existing_key!r}, not "
                f"{requested_key!r}."
            ),
        )
    return existing_key


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Return success only when the API can execute a query against PostgreSQL."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post(
    "/tables/upsert",
    response_model=TableUpsertResponse,
    status_code=status.HTTP_200_OK,
)
def upsert_table(
    request: TableUpsertRequest,
    db: Session = Depends(get_db),
) -> TableUpsertResponse:
    """Create with a supplied key or upsert using an existing table's key."""
    table_name = validate_identifier(request.table_name, "table_name")
    requested_key = (
        validate_identifier(request.primary_key, "primary_key")
        if request.primary_key is not None
        else None
    )
    incoming_columns = {column_name for row in request.fields for column_name in row}
    for column_name in incoming_columns:
        validate_identifier(column_name, "Field name")

    connection = db.connection()
    table_exists = inspect(connection).has_table(table_name, schema=SCHEMA_NAME)

    try:
        if table_exists:
            table = Table(
                table_name,
                MetaData(),
                schema=SCHEMA_NAME,
                autoload_with=connection,
            )
            unknown_columns = incoming_columns - set(table.c.keys())
            if unknown_columns:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Incoming fields do not exist in the table: "
                        f"{', '.join(sorted(unknown_columns))}."
                    ),
                )
            primary_key = resolve_existing_primary_key(table, requested_key)
        else:
            if requested_key is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "primary_key is required when creating a new table."
                    ),
                )
            primary_key = requested_key
            table = table_from_fields(table_name, primary_key, request.fields)
            table.create(bind=connection)

        if any(primary_key not in row or row[primary_key] is None for row in request.fields):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Every row must contain a non-null primary_key value.",
            )

        unique_fields = deduplicate_rows_by_primary_key(
            request.fields, primary_key
        )
        rows = normalized_rows(unique_fields, incoming_columns)
        statement = insert(table).values(rows)
        update_columns = {
            column_name: statement.excluded[column_name]
            for column_name in incoming_columns
            if column_name != primary_key
        }
        if update_columns:
            statement = statement.on_conflict_do_update(
                index_elements=[table.c[primary_key]],
                set_=update_columns,
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=[table.c[primary_key]]
            )

        db.execute(statement)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from error

    return TableUpsertResponse(
        table_name=table_name,
        primary_key=primary_key,
        created=not table_exists,
        rows_upserted=len(rows),
    )
