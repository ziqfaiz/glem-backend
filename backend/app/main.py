from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import OutputRecord
from .schemas import OutputUpsertRequest, OutputUpsertResponse


app = FastAPI(title=get_settings().app_name, version="1.0.0")


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post("/output/upsert", response_model=OutputUpsertResponse)
def upsert_output(
    request: OutputUpsertRequest,
    db: Session = Depends(get_db),
) -> OutputUpsertResponse:
    records_by_key = {
        (item.uuid, item.created_dt): item.model_dump() for item in request.items
    }
    records = list(records_by_key.values())

    statement = insert(OutputRecord).values(records)
    statement = statement.on_conflict_do_update(
        index_elements=[OutputRecord.uuid, OutputRecord.created_dt],
        set_={
            "sender_id": statement.excluded.sender_id,
            "sender_name": statement.excluded.sender_name,
            "trx_date": statement.excluded.trx_date,
            "receiver_id": statement.excluded.receiver_id,
            "receiver_name": statement.excluded.receiver_name,
            "type": statement.excluded.type,
            "dc": statement.excluded.dc,
            "amount": statement.excluded.amount,
            "status": statement.excluded.status,
        },
    )
    db.execute(statement)
    db.commit()

    return OutputUpsertResponse(upserted=len(records))

