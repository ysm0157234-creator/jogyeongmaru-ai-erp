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
    source: str = "shipment_overview"


def normalize(value: Any) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())


def search_terms(name: str) -> list[str]:
    values = {
        name,
        name.replace("spp.", ""),
        name.replace("Sunlover", "Sun Lover"),
        name.replace("Sun Lover", "Sunlover"),
        name.split()[-1] if name.split() else name,
    }
    return sorted(
        {normalize(value) for value in values if len(normalize(value)) >= 4},
        key=len,
        reverse=True,
    )


def find_variety_in_workbook(data: bytes, variety_name: str) -> ShipmentMatch:
    workbook = load_workbook(io.BytesIO(data), data_only=False)
    wanted = search_terms(variety_name)
    matches: list[tuple[int, ShipmentMatch]] = []

    for sheet in workbook.worksheets:
        header_row = 1
        description_col = None

        for row in range(1, min(sheet.max_row, 30) + 1):
            for col in range(1, sheet.max_column + 1):
                header = normalize(sheet.cell(row, col).value)
                if description_col is None and any(
                    key in header
                    for key in ("description", "품종", "품명", "product", "item")
                ):
                    description_col = col
                    header_row = row

        # 회사 Shipment Overview 규칙: H열이 Shipment 열이다.
        shipment_col = 8
        if sheet.max_column < shipment_col:
            continue

        headers = {
            col: str(sheet.cell(header_row, col).value or f"COL_{col}")
            for col in range(1, sheet.max_column + 1)
        }

        for row in range(header_row + 1, sheet.max_row + 1):
            row_text = " ".join(
                str(sheet.cell(row, col).value or "")
                for col in range(1, sheet.max_column + 1)
            )
            normalized_row = normalize(row_text)

            score = next(
                (100 - index for index, term in enumerate(wanted) if term in normalized_row),
                0,
            )
            if not score:
                continue

            shipment = str(sheet.cell(row, shipment_col).value or "").strip()
            description = (
                str(sheet.cell(row, description_col).value or "").strip()
                if description_col
                else row_text
            )
            values = {
                headers[col]: sheet.cell(row, col).value
                for col in range(1, sheet.max_column + 1)
                if sheet.cell(row, col).value not in (None, "")
            }
            values["Shipment(H열)"] = shipment

            matches.append(
                (
                    score,
                    ShipmentMatch(
                        sheet_name=sheet.title,
                        row_number=row,
                        description=description,
                        shipment=shipment,
                        values=values,
                    ),
                )
            )

    if not matches:
        raise LookupError(
            f"Shipment Overview에서 '{variety_name}' 품종을 찾지 못했습니다."
        )

    matches.sort(key=lambda item: item[0], reverse=True)
    best = matches[0][1]
    if not best.shipment:
        raise LookupError(
            f"품종은 찾았지만 같은 행 H열의 Shipment 값이 비어 있습니다. "
            f"(시트 {best.sheet_name}, 행 {best.row_number})"
        )
    return best
