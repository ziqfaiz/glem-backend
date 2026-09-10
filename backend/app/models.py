from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class OutputRecord(Base):
    __tablename__ = "output"
    __table_args__ = {"schema": "public"}

    uuid: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_dt: Mapped[date] = mapped_column(Date, primary_key=True)
    sender_id: Mapped[str | None] = mapped_column(Text)
    sender_name: Mapped[str | None] = mapped_column(Text)
    trx_date: Mapped[datetime | None] = mapped_column(DateTime)
    receiver_id: Mapped[str | None] = mapped_column(Text)
    receiver_name: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str | None] = mapped_column(Text)
    dc: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text)
