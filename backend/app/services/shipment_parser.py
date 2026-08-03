from __future__ import annotations
import io, re
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
    source: str = "shipment_overview"

def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())

def terms(name: str) -> list[str]:
    vals = {name, name.replace("spp.", ""), name.replace("Sunlover", "Sun Lover"), name.replace("Sun Lover", "Sunlover"), name.split()[-1]}
    return sorted({normalize(v) for v in vals if len(normalize(v)) >= 4}, key=len, reverse=True)

def find_variety_in_workbook(data: bytes, variety_name: str) -> ShipmentMatch:
    wb = load_workbook(io.BytesIO(data), data_only=False)
    wanted = terms(variety_name)
    found = []
    for ws in wb.worksheets:
        shipment_col, desc_col, header_row = None, None, 1
        for r in range(1, min(ws.max_row, 30) + 1):
            for c in range(1, ws.max_column + 1):
                h = normalize(ws.cell(r, c).value)
                if shipment_col is None and any(x in h for x in ("shipment", "container", "컨테이너", "선적")):
                    shipment_col, header_row = c, r
                if desc_col is None and any(x in h for x in ("description", "품종", "품명", "product", "item")):
                    desc_col, header_row = c, r
        if shipment_col is None and ws.max_column >= 8:
            shipment_col = 8
        headers = {c: str(ws.cell(header_row, c).value or f"COL_{c}") for c in range(1, ws.max_column + 1)}
        for r in range(header_row + 1, ws.max_row + 1):
            row_text = " ".join(str(ws.cell(r, c).value or "") for c in range(1, ws.max_column + 1))
            nr = normalize(row_text)
            score = next((100-i for i,t in enumerate(wanted) if t in nr), 0)
            if not score:
                continue
            shipment = str(ws.cell(r, shipment_col).value or "").strip() if shipment_col else ""
            description = str(ws.cell(r, desc_col).value or "").strip() if desc_col else row_text
            values = {headers[c]: ws.cell(r,c).value for c in range(1,ws.max_column+1) if ws.cell(r,c).value not in (None,"")}
            found.append((score, ShipmentMatch(ws.title,r,description,shipment,values)))
    if not found:
        raise LookupError(f"Shipment Overview에서 '{variety_name}' 품종을 찾지 못했습니다.")
    found.sort(key=lambda x:x[0], reverse=True)
    best = found[0][1]
    if not best.shipment:
        raise LookupError(f"품종은 찾았지만 같은 행의 Shipment 값이 비어 있습니다. (시트 {best.sheet_name}, 행 {best.row_number})")
    return best
