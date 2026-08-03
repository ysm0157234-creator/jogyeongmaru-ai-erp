from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field

class ReportBase(BaseModel):
    agency: str
    report_type: str
    report_date: date
    status: str = "작성 중"
    item_name: str
    variety_name: str
    specification: str = ""
    quantity: int = Field(gt=0)
    unit: str = "주"
    production_location: str = ""
    lot_no: str = ""
    customer: str = ""
    customer_address: str = ""
    manager: str = ""
    memo: str = ""

class ReportCreate(ReportBase):
    pass

class ReportUpdate(ReportBase):
    pass

class ReportResponse(ReportBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_by: int
    created_at: datetime
    updated_at: datetime

class DashboardResponse(BaseModel):
    total: int
    draft: int
    pending: int
    done: int
    production: int
    sales: int
