from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

class AIGenerateRequest(BaseModel):
    variety_name: str
    agency: str = "국립종자원"

class AIDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query_name: str
    agency: str
    status: str
    result_data: dict[str, Any]
    created_by: int
    created_at: datetime
