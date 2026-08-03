from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class AIDraft(Base):
    __tablename__ = "ai_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_name: Mapped[str] = mapped_column(String(255), index=True)
    agency: Mapped[str] = mapped_column(String(50), default="국립종자원")
    status: Mapped[str] = mapped_column(String(40), default="검토 대기")
    result_data: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
