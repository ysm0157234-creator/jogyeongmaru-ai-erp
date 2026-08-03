from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agency: Mapped[str] = mapped_column(String(50), index=True)
    report_type: Mapped[str] = mapped_column(String(50), index=True)
    report_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default="작성 중", index=True)

    item_name: Mapped[str] = mapped_column(String(100))
    variety_name: Mapped[str] = mapped_column(String(100))
    specification: Mapped[str] = mapped_column(String(100), default="")
    quantity: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(20), default="주")

    production_location: Mapped[str] = mapped_column(String(255), default="")
    lot_no: Mapped[str] = mapped_column(String(100), default="")
    customer: Mapped[str] = mapped_column(String(200), default="")
    customer_address: Mapped[str] = mapped_column(String(255), default="")
    manager: Mapped[str] = mapped_column(String(100), default="")
    memo: Mapped[str] = mapped_column(Text, default="")

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
