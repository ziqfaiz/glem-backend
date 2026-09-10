from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OutputTransaction(Base):
    __tablename__ = "output_table"
    __table_args__ = {"schema": "dev"}

    trx_uuid: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    created_dt: Mapped[date] = mapped_column(Date, primary_key=True)
    sender_name: Mapped[str] = mapped_column(Text, nullable=False)
    trx_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    receiver_name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    dc: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
