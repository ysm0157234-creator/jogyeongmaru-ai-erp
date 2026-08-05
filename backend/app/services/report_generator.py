from __future__ import annotations

import io
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm


COMPANY = {
    "representative": "황수영",
    "address": "경기도 평택시 진위면 서촌로 38-9",
    "company_name": "농업회사법인 주식회사 조경마루",
    "phone": "010-9377-3058",
    "seed_business_number": "제10-평택-2023-30-01호",
}


def _set_margins(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Mm(15)
    section.bottom_margin = Mm(15)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)


def _save(doc: Document) -> bytes:
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def build_main_report(
    variety_name: str,
    korean_name: str,
    scientific_name: str,
    shipment: str,
    characteristics: str,
    breeding_process: str,
    overall_image: bytes,
    closeup_image: bytes,
    origin_country: str = "네덜란드",
) -> bytes:
    doc = Document()
    _set_margins(doc)

    title = doc.add_heading("품종 생산·수입판매 신고서 검토안", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in [
        ("신고 구분", "수입 판매"),
        ("신고인", COMPANY["representative"]),
        ("법인 명칭", COMPANY["company_name"]),
        ("주소", COMPANY["address"]),
        ("전화번호", COMPANY["phone"]),
        ("품종명", variety_name),
        ("한글명", korean_name),
        ("학명", scientific_name),
        ("원산지", origin_country),
        ("Shipment", shipment),
        ("종자업 등록번호", COMPANY["seed_business_number"]),
    ]:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = str(value)

    doc.add_heading("품종의 특성", level=1)
    doc.add_paragraph(characteristics)

    doc.add_heading("품종의 육성과정", level=1)
    doc.add_paragraph(breeding_process)

    doc.add_heading("품종 사진", level=1)
    doc.add_paragraph("사진 1. 품종 전체 모습")
    doc.add_picture(io.BytesIO(overall_image), width=Mm(165))
    doc.add_paragraph("사진 2. 꽃 근접 모습")
    doc.add_picture(io.BytesIO(closeup_image), width=Mm(165))

    doc.add_paragraph(f"작성일: {date.today().isoformat()}")
    return _save(doc)


def build_characteristics_document(
    variety_name: str,
    korean_name: str,
    scientific_name: str,
    characteristics: str,
    overall_image: bytes,
    closeup_image: bytes,
) -> bytes:
    doc = Document()
    _set_margins(doc)
    doc.add_heading("품종 특성 설명", level=0)
    doc.add_paragraph(f"품종명: {variety_name}")
    doc.add_paragraph(f"한글명: {korean_name}")
    doc.add_paragraph(f"학명: {scientific_name}")
    doc.add_heading("주요 특성", level=1)
    doc.add_paragraph(characteristics)
    doc.add_heading("전체 모습", level=1)
    doc.add_picture(io.BytesIO(overall_image), width=Mm(165))
    doc.add_heading("꽃 근접 모습", level=1)
    doc.add_picture(io.BytesIO(closeup_image), width=Mm(165))
    return _save(doc)


def build_breeding_document(
    variety_name: str,
    korean_name: str,
    breeding_process: str,
    origin_country: str = "네덜란드",
) -> bytes:
    doc = Document()
    _set_margins(doc)
    doc.add_heading("품종 육성과정 설명", level=0)
    doc.add_paragraph(f"식물명: {korean_name}")
    doc.add_paragraph(f"품종명: {variety_name}")
    doc.add_paragraph(f"종자 또는 묘목 생산지: {origin_country}")
    doc.add_heading("육성과정", level=1)
    doc.add_paragraph(breeding_process)
    return _save(doc)


def build_sample_pledge_document(
    variety_name: str,
    korean_name: str,
) -> bytes:
    doc = Document()
    _set_margins(doc)
    title = doc.add_heading("품종생산·수입판매신고 시료제출 확약서", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in [
        ("신고인 성명", COMPANY["representative"]),
        ("주소", COMPANY["address"]),
        ("법인명칭", COMPANY["company_name"]),
        ("작물명", korean_name),
        ("품종명", variety_name),
    ]:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value

    doc.add_paragraph(
        "상기 품종은 영양번식작물에 해당하므로 신고 시 종자시료를 자체 보관하고, "
        "관계 기관에서 시료 제출을 요구할 때에는 지체 없이 제출할 것을 확약합니다."
    )
    doc.add_paragraph(f"{date.today().year}년 {date.today().month}월 {date.today().day}일")
    doc.add_paragraph(f"신고인: {COMPANY['representative']} (인)")
    return _save(doc)


def build_pdf_summary(
    variety_name: str,
    scientific_name: str,
    shipment: str,
    source_invoice: str,
    quarantine_file: str,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    y = height - 50
    c.setFont("Helvetica-Bold", 15)
    c.drawString(45, y, "Jogyeongmaru AI ERP - Package Summary")
    y -= 28
    c.setFont("Helvetica", 10)
    for line in [
        f"Variety: {variety_name}",
        f"Scientific name: {scientific_name}",
        f"Shipment: {shipment}",
        f"Invoice source: {source_invoice}",
        f"Quarantine source: {quarantine_file}",
        "Package requires two photographs: overall and flower close-up.",
    ]:
        c.drawString(45, y, line[:110])
        y -= 16
    c.save()
    return buffer.getvalue()
