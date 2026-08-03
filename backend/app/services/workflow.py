from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from urllib.request import Request, urlopen

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
        "적황색 줄무늬가 나타난다. 개화가 진행되면서 주황색에서 "
        "주황빛 적색으로 변화하며, 꽃은 크고 풍성한 겹꽃 형태이다."
    ),
    "breeding_process": (
        "상기 품종을 국내에 수입·유통하기 위하여 네덜란드 수출업체를 통해 "
        "적법하게 구근을 수입하였다."
    ),
}

DOC_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
]

def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip()

def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())

def variety_terms(name: str) -> list[str]:
    terms = [
        name,
        name.replace("Sunlover", "Sun Lover"),
        name.replace("Sun Lover", "Sunlover"),
        name.replace("spp.", "").strip(),
        name.split()[-1],
    ]
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))

def find_shipment_token(file: DriveFile, related: list[DriveFile]) -> str:
    patterns = [
        r"\b[A-Z]{4}\d{7}\b",
        r"\bH\d{5,}\b",
        r"\b[A-Z]{2,8}[-_ ]?\d{2,}\b",
    ]
    names = [file.name]
    parent_ids = set(file.parents or [])
    names.extend(item.name for item in related if item.id in parent_ids)

    for name in names:
        for pattern in patterns:
            match = re.search(pattern, name, flags=re.IGNORECASE)
            if match:
                return match.group(0).strip()

    return re.sub(r"\.(xlsx|xlsm|pdf)$", "", file.name, flags=re.I).strip()

def verify_file_contains(
    drive: GoogleDriveService,
    file: DriveFile,
    terms: list[str],
) -> tuple[bool, bytes | None]:
    lower = file.name.lower()
    if not lower.endswith((".xlsx", ".xlsm", ".pdf")):
        return False, None

    data = drive.download(file.id)
    if lower.endswith((".xlsx", ".xlsm")):
        return workbook_contains(data, terms), data
    return pdf_contains(data, terms), data

def fallback_search_variety(
    drive: GoogleDriveService,
    variety_name: str,
) -> tuple[ShipmentMatch, DriveFile, bytes, list[DriveFile]]:
    terms = variety_terms(variety_name)

    # Google Drive indexes text in many PDFs/Office documents. This returns a
    # small candidate set instead of downloading every file in the 2026 folder.
    candidates: dict[str, DriveFile] = {}
    for term in terms:
        for file in drive.search_files(
            term,
            name_only=False,
            mime_types=DOC_MIME_TYPES,
            limit=50,
        ):
            candidates[file.id] = file

    if not candidates:
        # Filename-only fallback for documents that are not text indexed.
        for file in drive.search_filename_terms(terms, limit_each=50):
            candidates[file.id] = file

    ordered = sorted(
        candidates.values(),
        key=lambda file: (
            0 if file.name.lower().endswith((".xlsx", ".xlsm")) else 1,
            file.name.lower(),
        ),
    )

    for file in ordered[:80]:
        try:
            found, data = verify_file_contains(drive, file, terms)
            if not found or data is None:
                continue

            related = drive.search_filename_terms(
                [file.name.rsplit(".", 1)[0]],
                limit_each=30,
            )
            shipment = find_shipment_token(file, related)
            return (
                ShipmentMatch(
                    sheet_name=file.name,
                    row_number=0,
                    description=variety_name,
                    shipment=shipment,
                    values={
                        "품종명": variety_name,
                        "검색 원본": file.name,
                        "검색 방식": "Google Drive 색인 검색",
                    },
                    source="drive_search_fallback",
                ),
                file,
                data,
                related,
            )
        except Exception:
            continue

    raise LookupError(
        f"Shipment Overview와 Google Drive 검색에서 '{variety_name}' 품종을 찾지 못했습니다."
    )

def find_invoice_candidates(
    drive: GoogleDriveService,
    shipment: str,
    matched_file: DriveFile | None,
) -> list[DriveFile]:
    terms = [shipment]
    if matched_file:
        terms.append(matched_file.name.rsplit(".", 1)[0])

    results: dict[str, DriveFile] = {}
    for term in terms:
        for file in drive.search_filename_terms([term], limit_each=100):
            if any(word in file.name.lower() for word in ("invoice", "인보이스")):
                results[file.id] = file

    # Shipment may be present inside document text but absent from filename.
    if shipment:
        for file in drive.search_files(
            shipment,
            name_only=False,
            mime_types=DOC_MIME_TYPES,
            limit=100,
        ):
            if any(word in file.name.lower() for word in ("invoice", "인보이스")):
                results[file.id] = file

    matched_parents = set(matched_file.parents or []) if matched_file else set()
    scored = []
    for file in results.values():
        score = 0
        if normalize(shipment) in normalize(file.name):
            score += 100
        if matched_parents.intersection(file.parents or []):
            score += 80
        if file.name.lower().endswith((".xlsx", ".xlsm")):
            score += 10
        scored.append((score, file))

    scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return [file for _, file in scored]

def download_web_image(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 Jogyeongmaru-ERP/2.3"})
        with urlopen(request, timeout=25) as response:
            if not response.headers.get("Content-Type", "").startswith("image/"):
                return None
            return response.read(12 * 1024 * 1024)
    except Exception:
        return None

def selected_photo(draft_data: dict | None, role: str) -> dict | None:
    if not draft_data:
        return None
    selected_id = draft_data.get("selected_images", {}).get(role)
    for image in draft_data.get("image_candidates", []):
        if image.get("id") == selected_id:
            return image
    return None

def run_workflow(variety_name: str, draft_data: dict | None = None) -> tuple[bytes, dict]:
    settings = get_settings()
    drive = GoogleDriveService()
    search_log: list[str] = []

    matched_file = None
    matched_data = None

    shipment_data = drive.download(settings.shipment_overview_file_id)
    try:
        match = find_variety_in_workbook(shipment_data, variety_name)
        search_log.append(
            f"Shipment Overview 검색 성공: {match.sheet_name} {match.row_number}행"
        )
    except LookupError as error:
        search_log.append(str(error))
        match, matched_file, matched_data, _ = fallback_search_variety(
            drive,
            variety_name,
        )
        search_log.append(
            f"Google Drive 보조 검색 성공: {matched_file.name}"
        )

    candidates = find_invoice_candidates(
        drive,
        match.shipment,
        matched_file,
    )

    selected = None
    output_name = None
    output_data = None
    mode = ""

    terms = variety_terms(variety_name)
    for file in candidates[:30]:
        try:
            data = drive.download(file.id)
            lower = file.name.lower()
            if lower.endswith((".xlsx", ".xlsm")):
                if workbook_contains(data, terms):
                    output_data = filter_invoice_xlsx(
                        data,
                        variety_name,
                        match.shipment,
                    )
                    output_name = f"{safe_name(variety_name)}_신고용_invoice.xlsx"
                    mode = "원본 XLSX에서 해당 품종 행만 남김"
                    selected = file
                    break
            elif lower.endswith(".pdf"):
                output_data, pages = extract_invoice_pdf_pages(
                    data,
                    variety_name,
                )
                output_name = f"{safe_name(variety_name)}_신고용_invoice.pdf"
                mode = f"원본 PDF에서 품종 포함 페이지 {pages}장 추출"
                selected = file
                break
        except Exception:
            continue

    if output_data is None and matched_file and matched_data:
        try:
            if matched_file.name.lower().endswith((".xlsx", ".xlsm")):
                output_data = filter_invoice_xlsx(
                    matched_data,
                    variety_name,
                    match.shipment,
                )
                output_name = f"{safe_name(variety_name)}_신고용_검색원본.xlsx"
                mode = f"보조 검색 원본에서 품종 행 추출: {matched_file.name}"
            elif matched_file.name.lower().endswith(".pdf"):
                output_data, pages = extract_invoice_pdf_pages(
                    matched_data,
                    variety_name,
                )
                output_name = f"{safe_name(variety_name)}_신고용_검색원본.pdf"
                mode = f"보조 검색 PDF에서 품종 페이지 {pages}장 추출"
        except Exception:
            pass

    if output_data is None:
        output_data = create_invoice_extract_xlsx(
            variety_name,
            match.shipment,
            match.values,
            selected.name if selected else (
                matched_file.name if matched_file else None
            ),
        )
        output_name = f"{safe_name(variety_name)}_신고용_invoice_발췌.xlsx"
        mode = "검색 결과 기반 신고용 인보이스 발췌본 신규 생성"

    data = draft_data or {}
    final_name = data.get("matched_name", SUNLOVER["matched_name"])
    final_korean_name = data.get("korean_name", SUNLOVER["korean_name"])
    final_scientific_name = data.get("scientific_name", SUNLOVER["scientific_name"])
    final_characteristics = data.get("characteristics_draft", SUNLOVER["characteristics"])
    final_breeding_process = data.get("breeding_process_draft", SUNLOVER["breeding_process"])

    overall_meta = selected_photo(data, "overall")
    closeup_meta = selected_photo(data, "closeup")
    overall_image = download_web_image(overall_meta.get("preview_url") if overall_meta else None)
    closeup_image = download_web_image(closeup_meta.get("preview_url") if closeup_meta else None)

    docx = build_docx(
        final_name,
        final_korean_name,
        final_scientific_name,
        match.shipment,
        final_characteristics,
        final_breeding_process,
        overall_image=overall_image,
        closeup_image=closeup_image,
    )
    pdf = build_pdf_summary(
        final_name,
        final_korean_name,
        final_scientific_name,
        match.shipment,
        final_characteristics,
        final_breeding_process,
    )

    manifest = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "variety": variety_name,
        "search_log": search_log,
        "shipment_result": {
            "source": match.source,
            "sheet_or_file": match.sheet_name,
            "row": match.row_number,
            "description": match.description,
            "shipment": match.shipment,
            "values": match.values,
        },
        "shipment_overview": {"shipment": match.shipment},
        "invoice_candidates": [
            {"id": file.id, "name": file.name}
            for file in candidates
        ],
        "selected_invoice": (
            {"id": selected.id, "name": selected.name}
            if selected else None
        ),
        "invoice_processing": mode,
        "selected_images": {"overall": overall_meta, "closeup": closeup_meta},
    }

    output = io.BytesIO()
    folder = safe_name(variety_name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/신고서_검토안.docx", docx)
        archive.writestr(f"{folder}/처리요약.pdf", pdf)
        archive.writestr(f"{folder}/{output_name}", output_data)
        if overall_image:
            archive.writestr(f"{folder}/사진_1_전체모습.jpg", overall_image)
        if closeup_image:
            archive.writestr(f"{folder}/사진_2_꽃근접.jpg", closeup_image)
        archive.writestr(
            f"{folder}/manifest.json",
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )
    return output.getvalue(), manifest
