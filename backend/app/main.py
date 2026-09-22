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
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .schemas import TableUpsertRequest, TableUpsertResponse


IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


app = FastAPI(title=get_settings().app_name, version="4.0.0")


def validate_identifier(value: str, label: str) -> str:
    """Reject unsafe SQL schema, table, and column identifiers from a request."""
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


def column_names_in_request_order(rows: list[dict[str, Any]]) -> list[str]:
    """Return each column name once, preserving its first appearance in JSON rows."""
    seen_columns: set[str] = set()
    ordered_columns: list[str] = []
    for row in rows:
        for column_name in row:
            if column_name not in seen_columns:
                seen_columns.add(column_name)
                ordered_columns.append(column_name)
    return ordered_columns


def table_from_rows(
    schema_name: str,
    table_name: str,
    primary_key: str,
    rows: list[dict[str, Any]],
    column_names: list[str],
) -> Table:
    """Build a table definition that preserves incoming JSON field order."""
    if not column_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="rows must contain at least one column.",
        )
    if primary_key not in column_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="primary_key must be present in rows.",
        )
    if any(primary_key not in row or row[primary_key] is None for row in rows):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Every row must contain a non-null primary_key value.",
        )

    columns = []
    for column_name in column_names:
        values = [row.get(column_name) for row in rows]
        columns.append(
            Column(
                column_name,
                infer_column_type(values),
                primary_key=column_name == primary_key,
                nullable=column_name != primary_key,
            )
        )

    return Table(table_name, MetaData(schema=schema_name), *columns)


def normalized_rows(
    rows: list[dict[str, Any]], column_names: list[str]
) -> list[dict[str, Any]]:
    """Give every insert row the same ordered column set, using NULL if absent."""
    return [
        {column_name: row.get(column_name) for column_name in column_names}
        for row in rows
    ]


def deduplicate_rows_by_primary_key(
    rows: list[dict[str, Any]], primary_key: str
) -> list[dict[str, Any]]:
    """Keep the final row for a repeated key, preventing one batch conflict error."""
    if any(isinstance(row[primary_key], (dict, list)) for row in rows):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="primary_key values must be scalar values, not objects or arrays.",
        )
    return list({row[primary_key]: row for row in rows}.values())


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
    """Create a keyed table or upsert request rows into an existing table."""
    schema_name = validate_identifier(request.schema_name, "schema")
    table_name = validate_identifier(request.table_name, "table_name")
    requested_key = (
        validate_identifier(request.primary_key, "primary_key")
        if request.primary_key is not None
        else None
    )
    column_names = column_names_in_request_order(request.rows)
    for column_name in column_names:
        validate_identifier(column_name, "Field name")

    connection = db.connection()
    inspector = inspect(connection)
    if not inspector.has_schema(schema_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Schema {schema_name!r} does not exist.",
        )
    table_exists = inspector.has_table(table_name, schema=schema_name)

    try:
        if table_exists:
            table = Table(
                table_name,
                MetaData(),
                schema=schema_name,
                autoload_with=connection,
            )
            unknown_columns = set(column_names) - set(table.c.keys())
            if unknown_columns:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Incoming rows contain fields that do not exist in the table: "
                        f"{', '.join(sorted(unknown_columns))}."
                    ),
                )
            primary_key = resolve_existing_primary_key(table, requested_key)
        else:
            if requested_key is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="primary_key is required when creating a new table.",
                )
            primary_key = requested_key
            table = table_from_rows(
                schema_name, table_name, primary_key, request.rows, column_names
            )
            table.create(bind=connection)

        if any(primary_key not in row or row[primary_key] is None for row in request.rows):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Every row must contain a non-null primary_key value.",
            )

        unique_rows = deduplicate_rows_by_primary_key(request.rows, primary_key)
        rows = normalized_rows(unique_rows, column_names)
        if table_exists:
            existing_keys = set(
                db.scalars(
                    select(table.c[primary_key]).where(
                        table.c[primary_key].in_([row[primary_key] for row in rows])
                    )
                ).all()
            )
            rows_updated = sum(
                row[primary_key] in existing_keys for row in rows
            )
        else:
            rows_updated = 0
        rows_inserted = len(rows) - rows_updated

        statement = insert(table).values(rows)
        update_columns = {
            column_name: statement.excluded[column_name]
            for column_name in column_names
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
        schema_name=schema_name,
        table_name=table_name,
        primary_key=primary_key,
        created=not table_exists,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
    )

