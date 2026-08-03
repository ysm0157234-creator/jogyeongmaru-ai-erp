import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.report import Report
from app.models.user import User
from app.schemas.report import (
    DashboardResponse,
    ReportCreate,
    ReportResponse,
    ReportUpdate,
)
from .deps import get_current_user

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.get("", response_model=list[ReportResponse])
def list_reports(
    search: str = Query(""),
    agency: str = Query(""),
    report_type: str = Query(""),
    status: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Report)

    if search:
        keyword = f"%{search}%"
        query = query.filter(
            or_(
                Report.item_name.ilike(keyword),
                Report.variety_name.ilike(keyword),
                Report.customer.ilike(keyword),
                Report.lot_no.ilike(keyword),
            )
        )
    if agency:
        query = query.filter(Report.agency == agency)
    if report_type:
        query = query.filter(Report.report_type == report_type)
    if status:
        query = query.filter(Report.status == status)

    return query.order_by(Report.id.desc()).all()

@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    reports = db.query(Report).all()
    return DashboardResponse(
        total=len(reports),
        draft=sum(r.status == "작성 중" for r in reports),
        pending=sum(r.status == "전송 대기" for r in reports),
        done=sum(r.status == "완료" for r in reports),
        production=sum(r.report_type == "생산 신고" for r in reports),
        sales=sum(r.report_type == "판매 신고" for r in reports),
    )

@router.get("/export.csv")
def export_csv(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    reports = db.query(Report).order_by(Report.id.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "신고일", "기관", "구분", "상태", "품목", "품종", "규격",
        "수량", "단위", "생산지", "로트번호", "거래처",
        "거래처주소", "담당자", "비고",
    ])

    for report in reports:
        writer.writerow([
            report.report_date,
            report.agency,
            report.report_type,
            report.status,
            report.item_name,
            report.variety_name,
            report.specification,
            report.quantity,
            report.unit,
            report.production_location,
            report.lot_no,
            report.customer,
            report.customer_address,
            report.manager,
            report.memo,
        ])

    data = ("﻿" + output.getvalue()).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="reports.csv"'},
    )

@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="신고 자료를 찾을 수 없습니다.")
    return report

@router.post("", response_model=ReportResponse, status_code=201)
def create_report(
    payload: ReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = Report(**payload.model_dump(), created_by=current_user.id)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report

@router.put("/{report_id}", response_model=ReportResponse)
def update_report(
    report_id: int,
    payload: ReportUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="신고 자료를 찾을 수 없습니다.")

    for key, value in payload.model_dump().items():
        setattr(report, key, value)

    db.commit()
    db.refresh(report)
    return report

@router.delete("/{report_id}", status_code=204)
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="신고 자료를 찾을 수 없습니다.")

    db.delete(report)
    db.commit()
