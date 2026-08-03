
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from pypdf import PdfReader, PdfWriter

def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())

def workbook_contains(data: bytes, terms: list[str]) -> bool:
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    targets = [normalize(term) for term in terms if term]
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            joined = normalize(" ".join(str(v or "") for v in row))
            if any(target and target in joined for target in targets):
                return True
    return False

def filter_invoice_xlsx(
    source_data: bytes,
    variety_name: str,
    shipment_number: str,
) -> bytes:
    source = load_workbook(io.BytesIO(source_data))
    target = normalize(variety_name)
    cultivar = normalize(variety_name.split()[-1])

    for ws in source.worksheets:
        rows_to_keep: set[int] = set()
        matched_rows: set[int] = set()
        for row in range(1, ws.max_row + 1):
            joined = normalize(
                " ".join(str(ws.cell(row, col).value or "") for col in range(1, ws.max_column + 1))
            )
            if target in joined or (cultivar and cultivar in joined):
                matched_rows.add(row)

        if matched_rows:
            # Keep header/metadata area and matched rows. Also keep nearby totals.
            first_match = min(matched_rows)
            for row in range(1, first_match):
                rows_to_keep.add(row)
            for row in matched_rows:
                rows_to_keep.add(row)
            for row in range(max(matched_rows) + 1, min(ws.max_row, max(matched_rows) + 3) + 1):
                joined = normalize(
                    " ".join(str(ws.cell(row, col).value or "") for col in range(1, ws.max_column + 1))
                )
                if any(k in joined for k in ["total", "subtotal", "합계"]):
                    rows_to_keep.add(row)

            for row in range(ws.max_row, 0, -1):
                if row not in rows_to_keep:
                    ws.delete_rows(row)

            ws["A1"] = ws["A1"].value or "신고용 인보이스"
            ws["A2"] = f"Filtered for: {variety_name}"
            ws["A3"] = f"Shipment: {shipment_number}"

    buffer = io.BytesIO()
    source.save(buffer)
    return buffer.getvalue()

def extract_invoice_pdf_pages(source_data: bytes, variety_name: str) -> tuple[bytes, int]:
    reader = PdfReader(io.BytesIO(source_data))
    writer = PdfWriter()
    target = normalize(variety_name)
    cultivar = normalize(variety_name.split()[-1])
    matched = 0
    for page in reader.pages:
        text = normalize(page.extract_text() or "")
        if target in text or (cultivar and cultivar in text):
            writer.add_page(page)
            matched += 1
    if matched == 0:
        raise LookupError("PDF 인보이스에서 품종명이 포함된 페이지를 찾지 못했습니다.")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), matched

def create_invoice_extract_xlsx(
    variety_name: str,
    shipment_number: str,
    shipment_values: dict[str, Any],
    source_invoice_name: str | None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "신고용 인보이스 발췌"
    ws.append(["신고용 인보이스 발췌본"])
    ws.append(["품종명", variety_name])
    ws.append(["Shipment", shipment_number])
    ws.append(["원본 인보이스", source_invoice_name or "미확인"])
    ws.append([])
    ws.append(["Shipment Overview 원본 항목", "값"])
    for key, value in shipment_values.items():
        ws.append([key, value])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 50
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()

def pdf_contains(data: bytes, terms: list[str]) -> bool:
    reader = PdfReader(io.BytesIO(data))
    targets = [normalize(t) for t in terms if t]
    return any(any(t and t in normalize(page.extract_text() or "") for t in targets) for page in reader.pages)
