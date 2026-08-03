from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.services.drive_service import (
    DriveFile,
    FOLDER_MIME,
    GoogleDriveService,
)
from app.services.invoice_processor import (
    create_invoice_extract_xlsx,
    extract_invoice_pdf_pages,
    filter_invoice_xlsx,
    pdf_contains,
    workbook_contains,
)
from app.services.report_generator import build_docx, build_pdf_summary
from app.services.shipment_parser import ShipmentMatch, find_variety_in_workbook


SUNLOVER = {
    "matched_name": "Tulipa spp. Sunlover",
    "korean_name": "튤립 썬러버",
    "scientific_name": "Tulipa 'Sun Lover'",
    "characteristics": (
        "겹꽃형 튤립 품종으로 개화 초기에는 황금빛 노란색을 띠고 "
        "개화가 진행되면서 주황빛 적색으로 변화한다."
    ),
    "breeding_process": (
        "상기 품종을 국내에 수입·유통하기 위하여 네덜란드 수출업체를 통해 "
        "적법하게 구근을 수입하였다."
    ),
}

DOCUMENT_EXTENSIONS = (".xlsx", ".xlsm", ".pdf")


def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip()


def variety_terms(name: str) -> list[str]:
    values = [
        name,
        name.replace("Sunlover", "Sun Lover"),
        name.replace("Sun Lover", "Sunlover"),
        name.replace("spp.", "").strip(),
        name.split()[-1] if name.split() else name,
    ]
    return list(dict.fromkeys(value for value in values if value))


def is_invoice(file: DriveFile) -> bool:
    lower = file.name.lower()
    return (
        file.mime_type != FOLDER_MIME
        and lower.endswith(DOCUMENT_EXTENSIONS)
        and ("invoice" in lower or "인보이스" in lower)
    )


def file_contains(
    drive: GoogleDriveService,
    file: DriveFile,
    terms: list[str],
) -> tuple[bool, bytes]:
    data = drive.download(file.id)
    lower = file.name.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return workbook_contains(data, terms), data
    if lower.endswith(".pdf"):
        return pdf_contains(data, terms), data
    return False, data


def choose_invoice_from_folder(
    drive: GoogleDriveService,
    folder: DriveFile,
    variety_name: str,
) -> tuple[DriveFile, bytes]:
    files = drive.walk(folder.id, max_depth=3, max_items=500)
    invoices = [file for file in files if is_invoice(file)]
    if not invoices:
        raise LookupError(
            f"'{folder.name}' 폴더 안에서 Invoice 파일을 찾지 못했습니다."
        )

    terms = variety_terms(variety_name)
    for file in sorted(invoices, key=lambda item: item.name.lower()):
        try:
            contains, data = file_contains(drive, file, terms)
            if contains:
                return file, data
        except Exception:
            continue

    # 정확한 품종이 없어도 해당 Shipment 폴더의 첫 인보이스를 사용한다.
    first = sorted(invoices, key=lambda item: item.name.lower())[0]
    return first, drive.download(first.id)


def fallback_tulipa_invoice(
    drive: GoogleDriveService,
    import_folder_id: str,
) -> tuple[DriveFile, bytes]:
    # Shipment Overview에 품종이 없을 때는 2026수입 안에서 Tulipa가 들어간
    # 아무 인보이스를 양식으로 사용한다.
    files = drive.walk(import_folder_id, max_depth=5, max_items=1800)
    invoices = [file for file in files if is_invoice(file)]

    for file in sorted(invoices, key=lambda item: item.name.lower()):
        try:
            contains, data = file_contains(drive, file, ["Tulipa"])
            if contains:
                return file, data
        except Exception:
            continue

    raise LookupError(
        "Shipment Overview에 품종이 없고, 2026수입 폴더에서도 "
        "Tulipa가 포함된 인보이스를 찾지 못했습니다."
    )


def process_invoice(
    source: DriveFile,
    source_data: bytes,
    variety_name: str,
    shipment: str,
    overview_values: dict,
) -> tuple[bytes, str, str]:
    lower = source.name.lower()

    try:
        if lower.endswith((".xlsx", ".xlsm")):
            output = filter_invoice_xlsx(
                source_data,
                variety_name,
                shipment,
            )
            return (
                output,
                f"{safe_name(variety_name)}_신고용_invoice.xlsx",
                f"원본 XLSX 가공: {source.name}",
            )

        if lower.endswith(".pdf"):
            output, pages = extract_invoice_pdf_pages(
                source_data,
                variety_name,
            )
            return (
                output,
                f"{safe_name(variety_name)}_신고용_invoice.pdf",
                f"원본 PDF 품종 페이지 {pages}장 추출: {source.name}",
            )
    except Exception:
        pass

    return (
        create_invoice_extract_xlsx(
            variety_name,
            shipment,
            overview_values,
            source.name,
        ),
        f"{safe_name(variety_name)}_신고용_invoice_발췌.xlsx",
        f"원본 인보이스 양식을 참고한 신규 발췌본: {source.name}",
    )


def download_web_image(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        request = Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 Jogyeongmaru-ERP/3.0"},
        )
        with urlopen(request, timeout=25) as response:
            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
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


def run_workflow(
    variety_name: str,
    draft_data: dict | None = None,
) -> tuple[bytes, dict]:
    settings = get_settings()
    drive = GoogleDriveService()
    search_log: list[str] = []

    shipment_bytes = drive.download(settings.shipment_overview_file_id)
    overview_values: dict = {}
    matched_folder: DriveFile | None = None

    try:
        match = find_variety_in_workbook(shipment_bytes, variety_name)
        overview_values = match.values
        search_log.append(
            f"Shipment Overview에서 품종 발견: {match.sheet_name} {match.row_number}행"
        )
        search_log.append(f"H열 Shipment 값: {match.shipment}")

        matched_folder = drive.find_child_folder(
            settings.import_2026_folder_id,
            match.shipment,
        )
        if not matched_folder:
            raise LookupError(
                f"2026수입 바로 아래에서 Shipment 폴더 "
                f"'{match.shipment}'를 찾지 못했습니다."
            )

        search_log.append(f"Shipment 폴더 발견: {matched_folder.name}")
        source_invoice, source_data = choose_invoice_from_folder(
            drive,
            matched_folder,
            variety_name,
        )
        search_log.append(f"폴더 내부 인보이스 선택: {source_invoice.name}")
        source_mode = "shipment_overview_h_column"

    except LookupError as primary_error:
        search_log.append(str(primary_error))
        source_invoice, source_data = fallback_tulipa_invoice(
            drive,
            settings.import_2026_folder_id,
        )
        search_log.append(
            f"보조 검색: 2026수입에서 Tulipa 포함 인보이스 선택: "
            f"{source_invoice.name}"
        )
        match = ShipmentMatch(
            sheet_name="2026수입 직접 검색",
            row_number=0,
            description=variety_name,
            shipment="Shipment Overview 미발견",
            values={
                "품종명": variety_name,
                "검색 기준": "Tulipa가 포함된 아무 인보이스",
            },
            source="tulipa_invoice_fallback",
        )
        overview_values = match.values
        source_mode = "tulipa_any_invoice_fallback"

    invoice_data, invoice_name, invoice_mode = process_invoice(
        source_invoice,
        source_data,
        variety_name,
        match.shipment,
        overview_values,
    )

    data = draft_data or {}
    final_name = data.get("matched_name", SUNLOVER["matched_name"])
    final_korean_name = data.get("korean_name", SUNLOVER["korean_name"])
    final_scientific_name = data.get(
        "scientific_name",
        SUNLOVER["scientific_name"],
    )
    final_characteristics = data.get(
        "characteristics_draft",
        SUNLOVER["characteristics"],
    )
    final_breeding_process = data.get(
        "breeding_process_draft",
        SUNLOVER["breeding_process"],
    )

    overall_meta = selected_photo(data, "overall")
    closeup_meta = selected_photo(data, "closeup")
    overall_image = download_web_image(
        overall_meta.get("preview_url") if overall_meta else None
    )
    closeup_image = download_web_image(
        closeup_meta.get("preview_url") if closeup_meta else None
    )

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
        "search_mode": source_mode,
        "search_log": search_log,
        "shipment_result": {
            "source": match.source,
            "sheet_or_file": match.sheet_name,
            "row": match.row_number,
            "shipment_h_column": match.shipment,
            "values": match.values,
        },
        "matched_folder": (
            {"id": matched_folder.id, "name": matched_folder.name}
            if matched_folder
            else None
        ),
        "source_invoice": {
            "id": source_invoice.id,
            "name": source_invoice.name,
        },
        "invoice_processing": invoice_mode,
        "selected_images": {
            "overall": overall_meta,
            "closeup": closeup_meta,
        },
        # 기존 라우터 호환
        "shipment_overview": {"shipment": match.shipment},
    }

    output = io.BytesIO()
    folder = safe_name(variety_name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{folder}/신고서_검토안.docx", docx)
        archive.writestr(f"{folder}/처리요약.pdf", pdf)
        archive.writestr(f"{folder}/{invoice_name}", invoice_data)
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
