from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime

from app.core.config import get_settings
from app.services.drive_service import GoogleDriveService, DriveFile
from app.services.shipment_parser import ShipmentMatch, find_variety_in_workbook
from app.services.invoice_processor import (
    workbook_contains,
    pdf_contains,
    filter_invoice_xlsx,
    extract_invoice_pdf_pages,
    create_invoice_extract_xlsx,
)
from app.services.report_generator import build_docx, build_pdf_summary


SUNLOVER = {
    "matched_name": "Tulipa spp. Sunlover",
    "korean_name": "튤립 썬러버",
    "scientific_name": "Tulipa 'Sun Lover'",
    "characteristics": (
        "겹꽃형 튤립 품종으로 개화 초기에는 황금빛 노란색을 띠고 "
        "개화가 진행되면서 주황빛 적색으로 변화한다."
    ),
    "breeding_process": (
        "상기 품종을 국내에 수입·유통하기 위하여 "
        "네덜란드 수출업체를 통해 적법하게 구근을 수입하였다."
    ),
}


DOCUMENT_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
]


def safe_name(value: str) -> str:
    return re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        value,
    ).strip()


def norm(value: str) -> str:
    return re.sub(
        r"[^a-z0-9가-힣]+",
        "",
        str(value or "").lower(),
    )


def variety_terms(variety_name: str) -> list[str]:
    terms = [
        variety_name,
        variety_name.replace(
            "Sunlover",
            "Sun Lover",
        ),
        variety_name.replace(
            "Sun Lover",
            "Sunlover",
        ),
        variety_name.replace(
            "spp.",
            "",
        ).strip(),
        variety_name.split()[-1],
    ]

    return list(
        dict.fromkeys(
            term.strip()
            for term in terms
            if term.strip()
        )
    )


def file_contains_variety(
    drive: GoogleDriveService,
    file: DriveFile,
    variety_name: str,
) -> tuple[bool, bytes | None]:
    lower_name = file.name.lower()

    if not lower_name.endswith(
        (
            ".xlsx",
            ".xlsm",
            ".pdf",
        )
    ):
        return False, None

    data = drive.download(file.id)
    terms = variety_terms(variety_name)

    if lower_name.endswith(
        (
            ".xlsx",
            ".xlsm",
        )
    ):
        return workbook_contains(
            data,
            terms,
        ), data

    return pdf_contains(
        data,
        terms,
    ), data


def extract_shipment_from_name(
    file: DriveFile,
) -> str:
    patterns = [
        r"\b[A-Z]{4}\d{7}\b",
        r"\bH\d{5,}\b",
        r"\b[A-Z]{2,8}[-_ ]?\d{2,}\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            file.name,
            flags=re.IGNORECASE,
        )

        if match:
            return match.group(0).strip()

    return re.sub(
        r"\.(xlsx|xlsm|pdf)$",
        "",
        file.name,
        flags=re.IGNORECASE,
    ).strip()


def search_variety_in_drive(
    drive: GoogleDriveService,
    variety_name: str,
) -> tuple[
    ShipmentMatch,
    DriveFile,
    bytes,
]:
    candidates: dict[str, DriveFile] = {}

    for term in variety_terms(variety_name):
        try:
            results = drive.search_files(
                term,
                name_only=False,
                mime_types=DOCUMENT_MIME_TYPES,
                limit=50,
            )

            for file in results:
                candidates[file.id] = file

        except Exception:
            continue

    if not candidates:
        for term in variety_terms(variety_name):
            try:
                results = drive.search_files(
                    term,
                    name_only=True,
                    mime_types=DOCUMENT_MIME_TYPES,
                    limit=50,
                )

                for file in results:
                    candidates[file.id] = file

            except Exception:
                continue

    ordered = sorted(
        candidates.values(),
        key=lambda file: (
            0
            if file.name.lower().endswith(
                (
                    ".xlsx",
                    ".xlsm",
                )
            )
            else 1,
            file.name.lower(),
        ),
    )

    for file in ordered[:50]:
        try:
            found, data = file_contains_variety(
                drive,
                file,
                variety_name,
            )

            if not found or data is None:
                continue

            shipment = extract_shipment_from_name(
                file,
            )

            match = ShipmentMatch(
                sheet_name=file.name,
                row_number=0,
                description=variety_name,
                shipment=shipment,
                values={
                    "품종명": variety_name,
                    "검색 원본": file.name,
                    "검색 방식": (
                        "Google Drive 문서 내용 검색"
                    ),
                },
                source="drive_search_fallback",
            )

            return match, file, data

        except Exception:
            continue

    raise LookupError(
        "Shipment Overview와 Google Drive 검색에서 "
        f"'{variety_name}' 품종을 찾지 못했습니다."
    )


def find_invoice_candidates(
    drive: GoogleDriveService,
    shipment: str,
    matched_file: DriveFile | None = None,
) -> list[DriveFile]:
    candidates: dict[str, DriveFile] = {}

    search_terms = []

    if shipment:
        search_terms.append(
            shipment,
        )

    if matched_file:
        search_terms.append(
            matched_file.name.rsplit(
                ".",
                1,
            )[0]
        )

    for term in search_terms:
        try:
            results = drive.search_files(
                term,
                name_only=True,
                limit=100,
            )

            for file in results:
                lower_name = file.name.lower()

                if any(
                    keyword in lower_name
                    for keyword in (
                        "invoice",
                        "인보이스",
                    )
                ):
                    candidates[file.id] = file

        except Exception:
            continue

    if shipment:
        try:
            results = drive.search_files(
                shipment,
                name_only=False,
                mime_types=DOCUMENT_MIME_TYPES,
                limit=100,
            )

            for file in results:
                lower_name = file.name.lower()

                if any(
                    keyword in lower_name
                    for keyword in (
                        "invoice",
                        "인보이스",
                    )
                ):
                    candidates[file.id] = file

        except Exception:
            pass

    matched_parents = (
        set(
            matched_file.parents or [],
        )
        if matched_file
        else set()
    )

    scored: list[
        tuple[int, DriveFile]
    ] = []

    for file in candidates.values():
        score = 0

        if (
            shipment
            and norm(shipment)
            in norm(file.name)
        ):
            score += 100

        if matched_parents.intersection(
            file.parents or [],
        ):
            score += 80

        if file.name.lower().endswith(
            (
                ".xlsx",
                ".xlsm",
            )
        ):
            score += 10

        scored.append(
            (
                score,
                file,
            )
        )

    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].name.lower(),
        )
    )

    return [
        file
        for _, file in scored
    ]


def create_invoice_output(
    drive: GoogleDriveService,
    variety_name: str,
    match: ShipmentMatch,
    candidates: list[DriveFile],
    matched_file: DriveFile | None,
    matched_data: bytes | None,
) -> tuple[
    bytes,
    str,
    str,
    DriveFile | None,
]:
    selected = None
    output_data = None
    output_name = None
    mode = ""

    terms = variety_terms(
        variety_name,
    )

    for file in candidates[:25]:
        try:
            data = drive.download(
                file.id,
            )

            lower_name = file.name.lower()

            if lower_name.endswith(
                (
                    ".xlsx",
                    ".xlsm",
                )
            ):
                if not workbook_contains(
                    data,
                    terms,
                ):
                    continue

                output_data = filter_invoice_xlsx(
                    data,
                    variety_name,
                    match.shipment,
                )

                output_name = (
                    f"{safe_name(variety_name)}"
                    "_신고용_invoice.xlsx"
                )

                mode = (
                    "원본 XLSX에서 "
                    "해당 품종 행만 남김"
                )

                selected = file
                break

            if lower_name.endswith(
                ".pdf",
            ):
                output_data, page_count = (
                    extract_invoice_pdf_pages(
                        data,
                        variety_name,
                    )
                )

                output_name = (
                    f"{safe_name(variety_name)}"
                    "_신고용_invoice.pdf"
                )

                mode = (
                    "원본 PDF에서 품종 포함 페이지 "
                    f"{page_count}장 추출"
                )

                selected = file
                break

        except Exception:
            continue

    if (
        output_data is None
        and matched_file
        and matched_data
    ):
        try:
            lower_name = (
                matched_file.name.lower()
            )

            if lower_name.endswith(
                (
                    ".xlsx",
                    ".xlsm",
                )
            ):
                output_data = (
                    filter_invoice_xlsx(
                        matched_data,
                        variety_name,
                        match.shipment,
                    )
                )

                output_name = (
                    f"{safe_name(variety_name)}"
                    "_신고용_검색원본.xlsx"
                )

                mode = (
                    "Google Drive 검색 원본에서 "
                    "품종 행 추출: "
                    f"{matched_file.name}"
                )

            elif lower_name.endswith(
                ".pdf",
            ):
                output_data, page_count = (
                    extract_invoice_pdf_pages(
                        matched_data,
                        variety_name,
                    )
                )

                output_name = (
                    f"{safe_name(variety_name)}"
                    "_신고용_검색원본.pdf"
                )

                mode = (
                    "Google Drive 검색 PDF에서 "
                    f"품종 페이지 {page_count}장 추출"
                )

        except Exception:
            pass

    if output_data is None:
        source_name = None

        if selected:
            source_name = selected.name

        elif matched_file:
            source_name = matched_file.name

        output_data = (
            create_invoice_extract_xlsx(
                variety_name,
                match.shipment,
                match.values,
                source_name,
            )
        )

        output_name = (
            f"{safe_name(variety_name)}"
            "_신고용_invoice_발췌.xlsx"
        )

        mode = (
            "검색 결과 기반 신고용 "
            "인보이스 발췌본 신규 생성"
        )

    return (
        output_data,
        output_name,
        mode,
        selected,
    )


def run_workflow(
    variety_name: str,
) -> tuple[bytes, dict]:
    settings = get_settings()
    drive = GoogleDriveService()

    search_log: list[str] = []

    matched_file = None
    matched_data = None

    shipment_bytes = drive.download(
        settings.shipment_overview_file_id,
    )

    try:
        match = find_variety_in_workbook(
            shipment_bytes,
            variety_name,
        )

        search_log.append(
            "Shipment Overview에서 "
            "품종과 Shipment를 찾았습니다."
        )

    except LookupError as error:
        search_log.append(
            str(error),
        )

        (
            match,
            matched_file,
            matched_data,
        ) = search_variety_in_drive(
            drive,
            variety_name,
        )

        search_log.append(
            "Google Drive 보조 검색으로 "
            f"품종을 찾았습니다: {matched_file.name}"
        )

    candidates = find_invoice_candidates(
        drive,
        match.shipment,
        matched_file,
    )

    (
        invoice_data,
        invoice_name,
        invoice_mode,
        selected_invoice,
    ) = create_invoice_output(
        drive,
        variety_name,
        match,
        candidates,
        matched_file,
        matched_data,
    )

    document = build_docx(
        SUNLOVER["matched_name"],
        SUNLOVER["korean_name"],
        SUNLOVER["scientific_name"],
        match.shipment,
        SUNLOVER["characteristics"],
        SUNLOVER["breeding_process"],
    )

    summary_pdf = build_pdf_summary(
        SUNLOVER["matched_name"],
        SUNLOVER["korean_name"],
        SUNLOVER["scientific_name"],
        match.shipment,
        SUNLOVER["characteristics"],
        SUNLOVER["breeding_process"],
    )

    manifest = {
        "generated_at": (
            datetime.utcnow().isoformat()
            + "Z"
        ),
        "variety": variety_name,
        "search_log": search_log,
        "shipment_result": {
            "source": match.source,
            "sheet_or_file": (
                match.sheet_name
            ),
            "row": match.row_number,
            "description": (
                match.description
            ),
            "shipment": (
                match.shipment
            ),
            "values": match.values,
        },
        "shipment_overview": {
            "shipment": (
                match.shipment
            ),
        },
        "invoice_candidates": [
            {
                "id": file.id,
                "name": file.name,
            }
            for file in candidates
        ],
        "selected_invoice": (
            {
                "id": (
                    selected_invoice.id
                ),
                "name": (
                    selected_invoice.name
                ),
            }
            if selected_invoice
            else None
        ),
        "invoice_processing": (
            invoice_mode
        ),
    }

    output = io.BytesIO()
    folder = safe_name(
        variety_name,
    )

    with zipfile.ZipFile(
        output,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            (
                f"{folder}/"
                "신고서_검토안.docx"
            ),
            document,
        )

        archive.writestr(
            (
                f"{folder}/"
                "처리요약.pdf"
            ),
            summary_pdf,
        )

        archive.writestr(
            (
                f"{folder}/"
                f"{invoice_name}"
            ),
            invoice_data,
        )

        archive.writestr(
            (
                f"{folder}/"
                "manifest.json"
            ),
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    return (
        output.getvalue(),
        manifest,
    )
