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
    tuple_,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .schemas import (
    SourceColumn,
    TableCreateRequest,
    TableCreateResponse,
    TableUpsertRequest,
    TableUpsertResponse,
)


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


app = FastAPI(title=get_settings().app_name, version="4.0.0")


def validate_identifier(value: str, label: str) -> str:
    """Reject unsafe SQL schema, table, and column identifiers from a request."""
    if not IDENTIFIER_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{label} must start with a letter and contain only letters, "
                "numbers, and underscores."
            ),
        )
    return value


def source_data_type_to_sqlalchemy(data_type: str):
    """Map supported source metadata types to the corresponding PostgreSQL type."""
    normalized_type = " ".join(data_type.upper().split())
    type_map = {
        "VARCHAR": Text,
        "CHARACTER VARYING": Text,
        "CHAR": Text,
        "CHARACTER": Text,
        "TEXT": Text,
        "STRING": Text,
        "BOOLEAN": Boolean,
        "BOOL": Boolean,
        "SMALLINT": BigInteger,
        "INTEGER": BigInteger,
        "INT": BigInteger,
        "BIGINT": BigInteger,
        "FLOAT": Float,
        "REAL": Float,
        "DOUBLE": Float,
        "DOUBLE PRECISION": Float,
        "DECIMAL": Float,
        "NUMERIC": Float,
        "DATE": Date,
        "TIMESTAMP": DateTime,
        "DATETIME": DateTime,
        "TIMESTAMPTZ": lambda: DateTime(timezone=True),
        "TIMESTAMP WITH TIME ZONE": lambda: DateTime(timezone=True),
        "UUID": lambda: PG_UUID(as_uuid=True),
        "JSON": JSONB,
        "JSONB": JSONB,
    }
    sqlalchemy_type = type_map.get(normalized_type)
    if sqlalchemy_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported source data_type: {data_type!r}.",
        )
    return sqlalchemy_type()


def coerce_value_for_column(value: Any, column_type: Any) -> Any:
    """Convert recognized JSON strings to the Python type expected by PostgreSQL."""
    if value is None:
        return None
    if isinstance(column_type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(column_type, Date) and isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(column_type, PG_UUID) and isinstance(value, str):
        return UUID(value)
    return value


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


def table_from_source_columns(
    schema_name: str,
    table_name: str,
    primary_key: list[str],
    source_columns: list[SourceColumn],
) -> Table:
    """Build a table definition from ordered source-system column metadata."""
    column_names = [column.column_name for column in source_columns]
    if len(set(column_names)) != len(column_names):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="columns must not contain duplicate column_name values.",
        )
    if len(set(primary_key)) != len(primary_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="primary_key must not contain duplicate column names.",
        )
    missing_primary_keys = set(primary_key) - set(column_names)
    if missing_primary_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "primary_key columns must be present in columns: "
                f"{', '.join(sorted(missing_primary_keys))}."
            ),
        )
    positions = [column.ordinal_position for column in source_columns]
    if len(set(positions)) != len(positions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="columns must not contain duplicate ordinal_position values.",
        )

    columns = []
    for source_column in sorted(source_columns, key=lambda column: column.ordinal_position):
        column_name = source_column.column_name
        nullable_value = source_column.is_nullable.upper()
        if nullable_value not in {"YES", "NO"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"is_nullable for {column_name!r} must be 'YES' or 'NO'."
                ),
            )
        columns.append(
            Column(
                column_name,
                source_data_type_to_sqlalchemy(source_column.data_type),
                primary_key=column_name in primary_key,
                nullable=False if column_name in primary_key else nullable_value == "YES",
            )
        )

    return Table(table_name, MetaData(schema=schema_name), *columns)


def normalized_rows(
    rows: list[dict[str, Any]], column_names: list[str], table: Table
) -> list[dict[str, Any]]:
    """Give rows one column set and coerce recognized values for their SQL type."""
    return [
        {
            column_name: coerce_value_for_column(
                row.get(column_name), table.c[column_name].type
            )
            for column_name in column_names
        }
        for row in rows
    ]


def deduplicate_rows_by_primary_key(
    rows: list[dict[str, Any]], primary_key: list[str]
) -> list[dict[str, Any]]:
    """Keep the final row for each single or composite primary-key value."""
    rows_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key_values = tuple(row[column_name] for column_name in primary_key)
        if any(isinstance(value, (dict, list)) for value in key_values):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="primary_key values must be scalar values, not objects or arrays.",
            )
        rows_by_key[key_values] = row
    return list(rows_by_key.values())


def resolve_existing_primary_key(table: Table) -> list[str]:
    """Discover the primary-key column or columns defined on an existing table."""
    existing_keys = list(table.primary_key.columns.keys())
    if not existing_keys:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Existing table must have at least one primary-key column.",
        )
    return existing_keys


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    """Return success only when the API can execute a query against PostgreSQL."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post(
    "/tables/create",
    response_model=TableCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_table(
    request: TableCreateRequest,
    db: Session = Depends(get_db),
) -> TableCreateResponse:
    """Create a new keyed table from source-system column metadata."""
    schema_name = validate_identifier(request.schema_name, "schema")
    table_name = validate_identifier(request.table_name, "table_name")
    primary_key = [
        validate_identifier(column_name, "primary_key")
        for column_name in request.primary_key
    ]
    for source_column in request.columns:
        column_name = source_column.column_name
        validate_identifier(column_name, "Field name")

    connection = db.connection()
    inspector = inspect(connection)
    if not inspector.has_schema(schema_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Schema {schema_name!r} does not exist.",
        )
    if inspector.has_table(table_name, schema=schema_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Table {schema_name}.{table_name} already exists.",
        )

    try:
        table = table_from_source_columns(
            schema_name, table_name, primary_key, request.columns
        )
        table.create(bind=connection)
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

    return TableCreateResponse(
        schema_name=schema_name,
        table_name=table_name,
        primary_key=primary_key,
        created=True,
    )


@app.post(
    "/tables/upsert",
    response_model=TableUpsertResponse,
    status_code=status.HTTP_200_OK,
)
def upsert_table(
    request: TableUpsertRequest,
    db: Session = Depends(get_db),
) -> TableUpsertResponse:
    """Insert or update rows in an existing table using its primary key."""
    schema_name = validate_identifier(request.schema_name, "schema")
    table_name = validate_identifier(request.table_name, "table_name")
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
    if not inspector.has_table(table_name, schema=schema_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Table {schema_name}.{table_name} does not exist. Create it first.",
        )

    try:
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
        primary_key = resolve_existing_primary_key(table)

        if any(
            any(column_name not in row or row[column_name] is None for column_name in primary_key)
            for row in request.rows
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Every row must contain non-null values for every primary-key column.",
            )

        unique_rows = deduplicate_rows_by_primary_key(request.rows, primary_key)
        rows = normalized_rows(unique_rows, column_names, table)
        primary_key_columns = [table.c[column_name] for column_name in primary_key]
        incoming_keys = [
            tuple(row[column_name] for column_name in primary_key) for row in rows
        ]
        if len(primary_key_columns) == 1:
            existing_keys = {
                (value,)
                for value in db.scalars(
                    select(primary_key_columns[0]).where(
                        primary_key_columns[0].in_([key[0] for key in incoming_keys])
                    )
                ).all()
            }
        else:
            existing_keys = {
                tuple(row)
                for row in db.execute(
                    select(*primary_key_columns).where(
                        tuple_(*primary_key_columns).in_(incoming_keys)
                    )
                ).all()
            }
        rows_updated = sum(key in existing_keys for key in incoming_keys)
        rows_inserted = len(rows) - rows_updated

        statement = insert(table).values(rows)
        update_columns = {
            column_name: statement.excluded[column_name]
            for column_name in column_names
            if column_name not in primary_key
        }
        if update_columns:
            statement = statement.on_conflict_do_update(
                index_elements=primary_key_columns,
                set_=update_columns,
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=primary_key_columns
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
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
    )
