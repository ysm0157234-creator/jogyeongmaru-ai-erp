from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

class AIGenerateRequest(BaseModel):
    variety_name: str
    agency: str = "국립종자원"

class AIDraftUpdateRequest(BaseModel):
    result_data: dict[str, Any]
    status: str = "검토 완료"

class AIFileGenerateRequest(BaseModel):
    variety_name: str
    agency: str = "국립종자원"
    draft_id: int

class AIDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query_name: str
    agency: str
    status: str
    result_data: dict[str, Any]
    created_by: int
    created_at: datetime
