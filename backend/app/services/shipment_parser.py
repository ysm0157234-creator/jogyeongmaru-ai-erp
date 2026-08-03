
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from openpyxl import load_workbook

@dataclass
class ShipmentMatch:
    sheet_name: str
    row_number: int
    description: str
    shipment: str
    values: dict[str, Any]

def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())

def find_header_row(ws, scan_rows: int = 30) -> tuple[int, dict[str, int]]:
    aliases = {
        "description": ["description", "품명", "품종", "product", "item"],
        "shipment": ["shipment", "container", "컨테이너", "선적"],
        "quantity": ["quantity", "qty", "수량"],
        "size": ["size", "규격"],
        "price": ["price", "단가"],
        "ref": ["ref", "reference", "참조"],
    }
    for row in range(1, min(ws.max_row, scan_rows) + 1):
        cells = {normalize(ws.cell(row, col).value): col for col in range(1, ws.max_column + 1)}
        mapping: dict[str, int] = {}
        for key, options in aliases.items():
            for raw, col in cells.items():
                if any(normalize(option) in raw for option in options):
                    mapping[key] = col
                    break
        if "description" in mapping and "shipment" in mapping:
            return row, mapping
    raise ValueError("Description/Shipment 헤더를 찾지 못했습니다.")

def find_variety_in_workbook(data: bytes, variety_name: str) -> ShipmentMatch:
    wb = load_workbook(io.BytesIO(data), data_only=True)
    target = normalize(variety_name)
    cultivar = normalize(variety_name.split()[-1])

    candidates: list[tuple[int, ShipmentMatch]] = []
    for ws in wb.worksheets:
        try:
            header_row, mapping = find_header_row(ws)
        except ValueError:
            continue

        headers = {
            col: str(ws.cell(header_row, col).value or "").strip()
            for col in range(1, ws.max_column + 1)
        }
        for row in range(header_row + 1, ws.max_row + 1):
            description = str(ws.cell(row, mapping["description"]).value or "").strip()
            norm_description = normalize(description)
            if not description:
                continue
            score = 0
            if target and target in norm_description:
                score = 100
            elif cultivar and cultivar in norm_description:
                score = 80
            if not score:
                continue

            shipment = str(ws.cell(row, mapping["shipment"]).value or "").strip()
            values = {
                headers[col] or f"COL_{col}": ws.cell(row, col).value
                for col in range(1, ws.max_column + 1)
                if ws.cell(row, col).value not in (None, "")
            }
            candidates.append(
                (
                    score,
                    ShipmentMatch(
                        sheet_name=ws.title,
                        row_number=row,
                        description=description,
                        shipment=shipment,
                        values=values,
                    ),
                )
            )

    if not candidates:
        raise LookupError(f"Shipment Overview에서 '{variety_name}' 품종을 찾지 못했습니다.")
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    if not best.shipment:
        raise LookupError("해당 품종 행에서 Shipment 번호가 비어 있습니다.")
    return best
