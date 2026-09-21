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
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .schemas import TableReplaceRequest, TableReplaceResponse


SCHEMA_NAME = "public"
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


app = FastAPI(title=get_settings().app_name, version="2.0.0")


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

    # A set makes it possible to detect whether values share one compatible type.
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


def table_from_fields(table_name: str, fields: list[dict[str, Any]]) -> Table:
    """Build an in-memory SQLAlchemy table definition from incoming row objects."""
    column_names = {column_name for row in fields for column_name in row}
    if not column_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fields must contain at least one column.",
        )

    columns = []
    for column_name in sorted(column_names):
        validate_identifier(column_name, "Field name")
        # Missing values are stored as NULL; their type is inferred from other rows.
        values = [row.get(column_name) for row in fields]
        columns.append(Column(column_name, infer_column_type(values), nullable=True))

    return Table(table_name, MetaData(schema=SCHEMA_NAME), *columns)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Return success only when the API can execute a query against PostgreSQL."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post(
    "/tables/replace",
    response_model=TableReplaceResponse,
    status_code=status.HTTP_200_OK,
)
def replace_table(
    request: TableReplaceRequest,
    db: Session = Depends(get_db),
) -> TableReplaceResponse:
    """Create a table or truncate an existing one, then insert all request rows."""
    table_name = validate_identifier(request.table_name, "table_name")
    connection = db.connection()
    # Reflection checks table existence before deciding whether to create or replace.
    inspector = inspect(connection)
    table_exists = inspector.has_table(table_name, schema=SCHEMA_NAME)

    try:
        if table_exists:
            table = Table(
                table_name,
                MetaData(),
                schema=SCHEMA_NAME,
                autoload_with=connection,
            )
            # Existing tables keep their schema; new/unrecognized fields are rejected.
            incoming_columns = {
                column_name for row in request.fields for column_name in row
            }
            unknown_columns = incoming_columns - set(table.c.keys())
            if unknown_columns:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Incoming fields do not exist in the table: "
                        f"{', '.join(sorted(unknown_columns))}."
                    ),
                )

            # Quote validated identifiers before building the PostgreSQL TRUNCATE command.
            preparer = connection.dialect.identifier_preparer
            qualified_table_name = ".".join(
                (preparer.quote(SCHEMA_NAME), preparer.quote(table_name))
            )
            db.execute(text(f"TRUNCATE TABLE {qualified_table_name}"))
        else:
            table = table_from_fields(table_name, request.fields)
            table.create(bind=connection)

        # DDL/DML run in one transaction: a failed insert rolls back the truncate/create.
        db.execute(table.insert(), request.fields)
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

    return TableReplaceResponse(
        table_name=table_name,
        created=not table_exists,
        rows_written=len(request.fields),
    )
