from __future__ import annotations
import io
from datetime import date
from docx import Document
from docx.shared import Mm

COMPANY = {
    "representative": "황수영",
    "address": "경기도 평택시 진위면 서촌로 38-9",
    "company_name": "농업회사법인 주식회사 조경마루",
    "phone": "010-9377-3058",
    "seed_business_number": "제10-평택-2023-30-01호",
}

def build_docx(
    variety_name: str,
    korean_name: str,
    scientific_name: str,
    shipment_number: str,
    characteristics: str,
    breeding_process: str,
    origin_country: str = "네덜란드",
    quarantine_number: str = "최종 확인 필요",
    overall_image: bytes | None = None,
    closeup_image: bytes | None = None,
) -> bytes:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Mm(15)
    section.bottom_margin = Mm(15)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)

    title = doc.add_heading("품종 수입 판매 신고서 검토안", level=0)
    title.alignment = 1

    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in [
        ("신고 구분", "수입 판매"),
        ("신고인", COMPANY["representative"]),
        ("법인 명칭", COMPANY["company_name"]),
        ("주소", COMPANY["address"]),
        ("전화번호", COMPANY["phone"]),
        ("학명 및 일반명", f"{korean_name}, {scientific_name}"),
        ("품종 명칭", variety_name),
        ("수입국(원산지)", origin_country),
        ("Shipment", shipment_number),
        ("종자업 등록번호", COMPANY["seed_business_number"]),
        ("검역합격 서류 발급번호", quarantine_number),
    ]:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value

    doc.add_heading("품종의 특성 설명", level=1)
    doc.add_paragraph(characteristics)

    doc.add_heading("품종육성 과정의 설명", level=1)
    doc.add_paragraph(f"식물명 : {korean_name}")
    doc.add_paragraph(f"품종명 : {variety_name}")
    doc.add_paragraph(f"종자 또는 묘목 생산지 : {origin_country}")
    doc.add_paragraph(breeding_process)

    doc.add_heading("품종 사진", level=1)
    doc.add_paragraph("사진 1. 품종 전체 모습")
    if overall_image:
        doc.add_picture(io.BytesIO(overall_image), width=Mm(135))
    else:
        doc.add_paragraph("사진 내려받기 실패")

    doc.add_paragraph("사진 2. 꽃 근접 모습")
    if closeup_image:
        doc.add_picture(io.BytesIO(closeup_image), width=Mm(135))
    else:
        doc.add_paragraph("사진 내려받기 실패")

    doc.add_paragraph(f"작성일: {date.today().isoformat()}")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

def build_pdf_summary(
    variety_name: str,
    korean_name: str,
    scientific_name: str,
    shipment_number: str,
    characteristics: str,
    breeding_process: str,
) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    y = height - 50
    c.setFont("Helvetica-Bold", 16)
    c.drawString(45, y, "Seed Import/Sales Report - Processing Summary")
    y -= 28
    c.setFont("Helvetica", 10)
    for line in [
        f"Variety: {variety_name}",
        f"Scientific name: {scientific_name}",
        f"Shipment: {shipment_number}",
        "DOCX includes one overall image and one flower close-up image.",
    ]:
        c.drawString(45, y, line[:110])
        y -= 16
    c.save()
    return buffer.getvalue()
