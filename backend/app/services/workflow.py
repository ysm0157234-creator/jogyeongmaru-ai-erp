from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.services.drive_service import DriveFile, FOLDER_MIME, GoogleDriveService
from app.services.invoice_processor import create_invoice_extract_xlsx, extract_invoice_pdf_pages, filter_invoice_xlsx
from app.services.report_generator import build_compatible_docx, build_pdf_summary
from app.services.hwp_template_service import HwpTemplateError, build_hwpx_report
from app.services.shipment_parser import find_variety_in_workbook
from app.services.upload_service import UploadError, get_upload


class RequiredFileMissingError(RuntimeError):
    pass


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())


def safe(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(value or "")).strip() or "report"


def quarantine_number_from_name(name: str) -> str:
    text = str(name or "")
    match = re.search(r"(?:제\s*)?([0-9]{2,4}[-_][0-9]{4,})", text)
    if match:
        return "제 " + match.group(1).replace("_", "-") + " 호"
    return ""


def is_folder(item: DriveFile) -> bool:
    return item.mime_type == FOLDER_MIME


def is_invoice(item: DriveFile) -> bool:
    name = item.name.lower()
    return (
        not is_folder(item)
        and name.endswith((".xlsx", ".xlsm", ".pdf"))
        and ("invoice" in name or "인보이스" in name)
        and "freight invoice" not in name
        and "freight_invoice" not in name
    )


def is_quarantine(item: DriveFile) -> bool:
    name = item.name.lower()
    return not is_folder(item) and name.endswith((".pdf", ".jpg", ".jpeg", ".png")) and any(word in name for word in ("검역", "quarantine", "phytosanitary", "phyto"))


def split_shipment(shipment: str) -> tuple[str, int]:
    match = re.match(r"^(.*?)[\s_-]*0*(\d+)$", str(shipment or "").strip())
    if not match:
        raise RequiredFileMissingError(f"Shipment 값에서 업체명과 컨테이너 번호를 분리할 수 없습니다: {shipment}")
    supplier = match.group(1).strip(" _-")
    if not supplier:
        raise RequiredFileMissingError(f"Shipment 값에 업체명이 없습니다: {shipment}")
    return supplier, int(match.group(2))


def match_folder(items: list[DriveFile], names: list[str]) -> DriveFile | None:
    folders = [item for item in items if is_folder(item)]
    targets = [norm(name) for name in names if name]
    for item in folders:
        if norm(item.name) in targets:
            return item
    for item in folders:
        item_name = norm(item.name)
        if any(target and (target in item_name or item_name in target) for target in targets):
            return item
    return None


def _supplier_core(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b(?:b\.?v\.?|bv|ltd\.?|limited|inc\.?|gmbh|company|co\.?)\b", " ", text)
    text = re.sub(r"(?:네덜란드|netherlands|holland|nederland)", " ", text)
    return norm(text)


def _supplier_match_score(folder_name: str, supplier: str) -> float:
    from difflib import SequenceMatcher

    folder_full = norm(folder_name)
    supplier_full = norm(supplier)
    folder_core = _supplier_core(folder_name)
    supplier_core = _supplier_core(supplier)

    if not folder_core or not supplier_core:
        return 0.0
    if folder_core == supplier_core:
        return 100.0
    if supplier_core in folder_core or folder_core in supplier_core:
        return 92.0
    if supplier_full and (supplier_full in folder_full or folder_full in supplier_full):
        return 88.0

    ratio = SequenceMatcher(None, folder_core, supplier_core).ratio()
    return ratio * 80.0


def find_supplier_folder(
    drive: GoogleDriveService,
    root_id: str,
    supplier: str,
) -> tuple[DriveFile | None, list[str]]:
    """
    지정된 연도 수입 폴더 바로 아래의 업체 폴더만 검사한다.

    Google Drive 전체 검색이나 다른 폴더 재귀 탐색은 하지 않는다.
    """
    candidates = [
        item
        for item in drive.list_children(root_id)
        if is_folder(item)
    ]

    ranked = sorted(
        (
            (_supplier_match_score(item.name, supplier), item)
            for item in candidates
        ),
        key=lambda pair: (-pair[0], pair[1].name.lower()),
    )

    if ranked and ranked[0][0] >= 68.0:
        return ranked[0][1], [item.name for _, item in ranked[:20]]

    return None, [item.name for _, item in ranked[:20]]


def find_supplier_across_import_folders(
    drive: GoogleDriveService,
    *,
    supplier: str,
    folders: list[tuple[str, str]],
) -> tuple[DriveFile, str]:
    """
    2025 → 2024 → 2023 순서로 지정된 폴더만 검사한다.
    """
    checked_by_year: list[str] = []

    for year_label, folder_id in folders:
        clean_id = str(folder_id or "").strip()
        if not clean_id:
            checked_by_year.append(f"{year_label}: 환경변수 누락")
            continue

        match, checked = find_supplier_folder(
            drive,
            clean_id,
            supplier,
        )
        if match:
            return match, year_label

        preview = ", ".join(checked[:12]) or "업체 폴더 없음"
        checked_by_year.append(f"{year_label}: {preview}")

    details = " / ".join(checked_by_year)
    raise RequiredFileMissingError(
        f"2025·2024·2023 수입 폴더에서 업체를 찾지 못했습니다: "
        f"{supplier}. 확인 결과: {details}"
    )


def find_shipping_folder(drive: GoogleDriveService, supplier: DriveFile) -> DriveFile:
    names = ["shipping document", "shipping documents", "shipping_document", "shippingdocument", "선적서류", "무역서류"]
    item = match_folder(drive.list_children(supplier.id), names)
    if not item:
        item = match_folder(drive.walk(supplier.id, max_depth=2, max_items=500), names)
    if not item:
        raise RequiredFileMissingError(f"{supplier.name} 안에서 shipping document 폴더를 찾지 못했습니다.")
    return item


def container_numbers(name: str) -> set[int]:
    match = re.search(r"(?i)container[\s_-]*([0-9,\s]+)", str(name or ""))
    return {int(value) for value in re.findall(r"\d+", match.group(1))} if match else set()


def find_container_folder(drive: GoogleDriveService, shipping: DriveFile, number: int) -> DriveFile:
    folders = [item for item in drive.list_children(shipping.id) if is_folder(item)]
    exact = [item for item in folders if number in container_numbers(item.name)]
    if exact:
        return sorted(exact, key=lambda item: item.name.lower())[0]
    item = match_folder(folders, [f"Container {number}", f"Container{number}", f"Container_{number}"])
    if item:
        return item
    available = ", ".join(item.name for item in folders[:25])
    raise RequiredFileMissingError(f"{shipping.name} 안에서 Container {number} 폴더를 찾지 못했습니다. 확인된 폴더: {available}")


def find_documents(drive: GoogleDriveService, container: DriveFile) -> tuple[DriveFile, DriveFile]:
    items = drive.list_children(container.id)
    invoices = sorted([item for item in items if is_invoice(item)], key=lambda item: (0 if "_invoice_" in item.name.lower() else 1, item.name.lower()))
    quarantines = sorted([item for item in items if is_quarantine(item)], key=lambda item: (0 if "phyto" in item.name.lower() else 1, item.name.lower()))
    if not invoices or not quarantines:
        sub = drive.walk(container.id, max_depth=2, max_items=300)
        if not invoices:
            invoices = sorted([item for item in sub if is_invoice(item)], key=lambda item: item.name.lower())
        if not quarantines:
            quarantines = sorted([item for item in sub if is_quarantine(item)], key=lambda item: item.name.lower())
    if not invoices:
        raise RequiredFileMissingError(f"{container.name} 안에서 일반 Invoice 파일을 찾지 못했습니다.")
    if not quarantines:
        raise RequiredFileMissingError(f"{container.name} 안에서 Phyto 또는 검역파일을 찾지 못했습니다.")
    return invoices[0], quarantines[0]


def selected_candidate(data: dict, role: str) -> dict | None:
    selected_id = data.get("selected_images", {}).get(role)
    if not selected_id:
        return None
    for item in data.get("image_candidates", []):
        if item.get("id") == selected_id:
            return item
    return None


def candidate_urls(candidate: dict) -> list[str]:
    output: list[str] = []
    for key in ("download_url", "preview_url", "backup_url", "backup_url_2", "image_url"):
        value = str(candidate.get(key) or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def _placeholder_image(title: str, subtitle: str) -> bytes:
    from PIL import ImageDraw, ImageFont

    image = Image.new("RGB", (1600, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 25, 1575, 975), outline="gray", width=4)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 56)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
        small = ImageFont.load_default()
    draw.text((100, 380), title, fill="black", font=font)
    draw.text((100, 480), subtitle, fill="gray", font=small)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def _image_from_selection(draft_data: dict, role: str, warnings: list[str]) -> bytes:
    candidate = selected_candidate(draft_data, role)
    label = "전체 모습" if role == "overall" else "근접"
    if candidate:
        upload_id = str(candidate.get("upload_id") or "").strip()
        if upload_id:
            try:
                return _normalize_image_to_jpeg(get_upload(upload_id).path.read_bytes())
            except (UploadError, OSError, RequiredFileMissingError) as exc:
                warnings.append(f"{label} 직접 업로드 사진을 읽지 못해 자리표시자를 사용했습니다: {exc}")
        urls = candidate_urls(candidate)
        if urls:
            try:
                return download_image(urls)
            except RequiredFileMissingError as exc:
                warnings.append(f"{label} 인터넷 사진 다운로드 실패로 자리표시자를 사용했습니다: {exc}")
    warnings.append(f"{label} 사진이 없어 직접 업로드가 필요합니다.")
    return _placeholder_image(f"{label} 사진 미첨부", "사이트에서 사진을 직접 선택하거나 업로드하세요.")


def _manual_file(draft_data: dict, role: str) -> tuple[bytes | None, str]:
    info = (draft_data.get("manual_files") or {}).get(role) or {}
    upload_id = str(info.get("upload_id") or "").strip()
    if not upload_id:
        return None, ""
    try:
        upload = get_upload(upload_id)
        return upload.path.read_bytes(), upload.original_name
    except (UploadError, OSError):
        return None, ""


def process_invoice(file: DriveFile, data: bytes, variety: str, shipment: str, values: dict) -> tuple[bytes, str]:
    try:
        if file.name.lower().endswith((".xlsx", ".xlsm")):
            return filter_invoice_xlsx(data, variety, shipment), f"06_{safe(variety)}_신고용_invoice.xlsx"
        if file.name.lower().endswith(".pdf"):
            output, _ = extract_invoice_pdf_pages(data, variety)
            return output, f"06_{safe(variety)}_신고용_invoice.pdf"
    except Exception:
        pass
    return create_invoice_extract_xlsx(variety, shipment, values, file.name), f"06_{safe(variety)}_신고용_invoice_발췌.xlsx"


def run_workflow(variety_name: str, draft_data: dict) -> tuple[bytes, dict]:
    settings = get_settings()
    warnings: list[str] = []

    shipment = ""
    shipment_sheet = ""
    shipment_row = None
    supplier_name = ""
    import_year = ""
    supplier_folder = ""
    shipping_folder = ""
    container_folder = ""
    invoice_name = ""
    quarantine_name = ""
    quarantine_number = ""
    invoice_output: bytes | None = None
    quarantine_data: bytes | None = None
    invoice_zip_name = ""

    # Drive 자료는 찾으면 첨부하고, 없더라도 신고서 초안 생성을 중단하지 않는다.
    manual_invoice, manual_invoice_name = _manual_file(draft_data, "invoice")
    manual_quarantine, manual_quarantine_name = _manual_file(draft_data, "quarantine")

    try:
        drive = GoogleDriveService()
        shipment_bytes = drive.download(settings.shipment_overview_file_id)
        match = find_variety_in_workbook(shipment_bytes, variety_name)
        shipment = match.shipment
        shipment_sheet = match.sheet_name
        shipment_row = match.row_number
        supplier_name, number = split_shipment(shipment)
        supplier, import_year = find_supplier_across_import_folders(
            drive,
            supplier=supplier_name,
            folders=[
                ("2025 수입", settings.import_2025_folder_id),
                ("2024 수입", settings.import_2024_folder_id),
                ("2023 수입", settings.import_2023_folder_id),
            ],
        )
        supplier_folder = supplier.name
        shipping = find_shipping_folder(drive, supplier)
        shipping_folder = shipping.name
        container = find_container_folder(drive, shipping, number)
        container_folder = container.name

        try:
            invoice, quarantine = find_documents(drive, container)
            invoice_name = invoice.name
            quarantine_name = quarantine.name
            invoice_data = drive.download(invoice.id)
            quarantine_data = drive.download(quarantine.id)
            invoice_output, invoice_zip_name = process_invoice(
                invoice, invoice_data, variety_name, shipment, match.values
            )
            quarantine_number = quarantine_number_from_name(quarantine.name)
        except (RequiredFileMissingError, DriveOperationError) as exc:
            warnings.append(f"Drive 첨부서류 자동수집 미완료: {exc}")
    except Exception as exc:
        warnings.append(f"Drive 자료 자동검색 미완료: {exc}")

    if manual_invoice:
        invoice_output = manual_invoice
        invoice_name = manual_invoice_name
        invoice_zip_name = f"06_{safe(manual_invoice_name)}"
        warnings.append("직접 업로드한 Invoice를 사용했습니다.")
    elif not invoice_output:
        warnings.append("Invoice가 첨부되지 않았습니다. 필요하면 사이트에서 직접 업로드하세요.")

    if manual_quarantine:
        quarantine_data = manual_quarantine
        quarantine_name = manual_quarantine_name
        quarantine_number = quarantine_number_from_name(manual_quarantine_name)
        warnings.append("직접 업로드한 검역·Phyto 파일을 사용했습니다.")
    elif not quarantine_data:
        warnings.append("검역합격증 또는 Phyto가 첨부되지 않았습니다. 필요하면 사이트에서 직접 업로드하세요.")

    overall_image = _image_from_selection(draft_data, "overall", warnings)
    closeup_image = _image_from_selection(draft_data, "closeup", warnings)

    final_name = draft_data.get("matched_name") or variety_name
    scientific_name = str(draft_data.get("scientific_name") or variety_name)
    characteristics = str(draft_data.get("characteristics_draft") or "").strip()
    breeding = str(draft_data.get("breeding_process_draft") or "").strip()
    if not characteristics:
        characteristics = "품종 특성 설명을 직접 입력해야 합니다."
        warnings.append("품종 특성 설명이 비어 있어 직접 입력 안내문을 사용했습니다.")
    if not breeding:
        breeding = "품종 육성과정을 직접 입력해야 합니다."
        warnings.append("품종 육성과정이 비어 있어 직접 입력 안내문을 사용했습니다.")
    draft_data["characteristics_draft"] = characteristics
    draft_data["breeding_process_draft"] = breeding

    template_path = Path(__file__).resolve().parent.parent / "templates" / "plant_import_report_template.hwpx"
    now = datetime.now()
    report_date_spaced = f"{now.year}년     {now.month}월     {now.day}일"
    hwpx_report: bytes | None = None
    try:
        hwpx_report = build_hwpx_report(
            template_path=template_path,
            result_data=draft_data,
            quarantine_number=quarantine_number,
            report_date_spaced=report_date_spaced,
            overall_image=overall_image,
            closeup_image=closeup_image,
            company={
                "representative": "황수영",
                "birth_date": "1985. 5. 15.",
                "address": "경기도 평택시 진위면 서촌로 38-9",
                "short_address": "경기 평택시 진위면 서촌로 38-9",
                "company_name": "농업회사법인 주식회사 조경마루",
                "phone": "010-9377-3058",
                "seed_business_number": "제10-평택-2023-30-01호",
            },
        )
        # HWPX가 최소한 ZIP 구조인지 생성 즉시 검사한다.
        with zipfile.ZipFile(io.BytesIO(hwpx_report)) as check:
            required = {"mimetype", "Contents/section0.xml"}
            if not required.issubset(set(check.namelist())):
                raise HwpTemplateError("생성된 HWPX 필수 항목이 누락되었습니다.")
    except Exception as exc:
        warnings.append(f"HWPX 생성 실패: {exc}. 호환용 DOCX는 계속 생성했습니다.")
        hwpx_report = None

    docx_report = build_compatible_docx(
        result_data=draft_data,
        shipment=shipment,
        quarantine_number=quarantine_number,
        overall_image=overall_image,
        closeup_image=closeup_image,
        warnings=warnings,
    )

    summary = build_pdf_summary(
        str(final_name), scientific_name, shipment, invoice_name, quarantine_name
    )

    manifest = {
        "build_version": "v19.1-stable-uploads-docx",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variety": variety_name,
        "matched_name": final_name,
        "scientific_name": scientific_name,
        "shipment": shipment,
        "shipment_sheet": shipment_sheet,
        "shipment_row": shipment_row,
        "import_year_folder": import_year,
        "supplier_folder": supplier_folder,
        "shipping_folder": shipping_folder,
        "container_folder": container_folder,
        "invoice": invoice_name,
        "quarantine": quarantine_name,
        "quarantine_number": quarantine_number,
        "report_formats": ["DOCX", *( ["HWPX"] if hwpx_report else [] )],
        "warnings": warnings,
    }

    output = io.BytesIO()
    base = safe(variety_name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if hwpx_report:
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.hwpx", hwpx_report)
        archive.writestr(f"{base}/01_품종_생산수입판매_신고서_호환용.docx", docx_report)
        if quarantine_data:
            archive.writestr(f"{base}/02_{safe(quarantine_name or '검역서류')}", quarantine_data)
        if invoice_output:
            archive.writestr(f"{base}/{invoice_zip_name or '03_신고용_invoice.bin'}", invoice_output)
        archive.writestr(f"{base}/04_품종전체사진.jpg", overall_image)
        archive.writestr(f"{base}/05_꽃근접사진.jpg", closeup_image)
        archive.writestr(f"{base}/06_처리요약.pdf", summary)
        archive.writestr(f"{base}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return output.getvalue(), manifest
