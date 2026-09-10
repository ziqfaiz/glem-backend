import os
import secrets
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from glem_backend.database import get_session
from glem_backend.models import OutputTransaction

app = FastAPI(
    title="Glem Write-back API",
    version="0.1.0",
    description="Receives transformed records from Glem and writes them to PostgreSQL.",
)


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected_api_key = os.getenv("API_KEY")
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication is not configured",
        )
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


class TransactionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    trx_uuid: UUID
    sender_name: str
    trx_date: datetime
    receiver_name: str
    type: str
    dc: Annotated[str, Field(alias="DC", min_length=1, max_length=1)]
    amount: int
    status: str
    created_dt: date


class UpsertRequest(BaseModel):
    items: Annotated[list[TransactionRecord], Field(alias="$items", min_length=1)]


class UpsertResponse(BaseModel):
    processed: int


@app.post(
    "/api/v1/records/upsert",
    response_model=UpsertResponse,
    dependencies=[Depends(require_api_key)],
    tags=["records"],
)
def upsert_records(
    payload: UpsertRequest,
    session: Annotated[Session, Depends(get_session)],
) -> UpsertResponse:
    records = [record.model_dump() for record in payload.items]
    statement = insert(OutputTransaction).values(records)
    statement = statement.on_conflict_do_update(
        index_elements=[OutputTransaction.trx_uuid, OutputTransaction.created_dt],
        set_={
            "sender_name": statement.excluded.sender_name,
            "trx_date": statement.excluded.trx_date,
            "receiver_name": statement.excluded.receiver_name,
            "type": statement.excluded.type,
            "dc": statement.excluded.dc,
            "amount": statement.excluded.amount,
            "status": statement.excluded.status,
        },
    )

    try:
        session.execute(statement)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database operation failed",
        ) from exc

    return UpsertResponse(processed=len(records))
