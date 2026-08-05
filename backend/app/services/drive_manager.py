from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.core.config import get_settings
from app.services.drive_service import DriveFile, DriveOperationError, FOLDER_MIME, GoogleDriveService
from app.services.invoice_processor import create_invoice_extract_xlsx, extract_invoice_pdf_pages, filter_invoice_xlsx
from app.services.service_errors import RequiredFileMissingError
from app.services.shipment_parser import find_variety_in_workbook
from app.services.upload_service import UploadError, get_upload


@dataclass
class DriveAssets:
    shipment: str = ""
    shipment_sheet: str = ""
    shipment_row: int | None = None
    supplier_name: str = ""
    import_year: str = ""
    supplier_folder: str = ""
    shipping_folder: str = ""
    container_folder: str = ""
    invoice_name: str = ""
    quarantine_name: str = ""
    quarantine_number: str = ""
    invoice_output: bytes | None = None
    quarantine_data: bytes | None = None
    invoice_zip_name: str = ""
    warnings: list[str] = field(default_factory=list)


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", str(value or "").lower())


def safe(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(value or "")).strip() or "report"


def quarantine_number_from_name(name: str) -> str:
    match = re.search(r"(?:제\s*)?([0-9]{2,4}[-_][0-9]{4,})", str(name or ""))
    return "제 " + match.group(1).replace("_", "-") + " 호" if match else ""


def is_folder(item: DriveFile) -> bool:
    return item.mime_type == FOLDER_MIME


def is_invoice(item: DriveFile) -> bool:
    name = item.name.lower()
    return not is_folder(item) and name.endswith((".xlsx", ".xlsm", ".pdf")) and ("invoice" in name or "인보이스" in name) and "freight invoice" not in name and "freight_invoice" not in name


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


def supplier_core(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\b(?:b\.?v\.?|bv|ltd\.?|limited|inc\.?|gmbh|company|co\.?)\b", " ", text)
    text = re.sub(r"(?:네덜란드|netherlands|holland|nederland|중국|china|프랑스|france|이탈리아|italy)", " ", text)
    return norm(text)


def supplier_match_score(folder_name: str, supplier: str) -> float:
    folder_full, supplier_full = norm(folder_name), norm(supplier)
    folder_core, supplier_core_value = supplier_core(folder_name), supplier_core(supplier)
    if not folder_core or not supplier_core_value:
        return 0.0
    if folder_core == supplier_core_value:
        return 100.0
    if supplier_core_value in folder_core or folder_core in supplier_core_value:
        return 92.0
    if supplier_full and (supplier_full in folder_full or folder_full in supplier_full):
        return 88.0
    return SequenceMatcher(None, folder_core, supplier_core_value).ratio() * 80.0


def find_supplier_folder(drive: GoogleDriveService, root_id: str, supplier: str) -> tuple[DriveFile | None, list[str]]:
    candidates = [item for item in drive.list_children(root_id) if is_folder(item)]
    ranked = sorted(((supplier_match_score(item.name, supplier), item) for item in candidates), key=lambda pair: (-pair[0], pair[1].name.lower()))
    if ranked and ranked[0][0] >= 68.0:
        return ranked[0][1], [item.name for _, item in ranked[:20]]
    return None, [item.name for _, item in ranked[:20]]


def find_supplier_across_import_folders(drive: GoogleDriveService, supplier: str, folders: list[tuple[str, str]]) -> tuple[DriveFile, str]:
    checked: list[str] = []
    for year_label, folder_id in folders:
        clean_id = str(folder_id or "").strip()
        if not clean_id:
            checked.append(f"{year_label}: 환경변수 누락")
            continue
        match, names = find_supplier_folder(drive, clean_id, supplier)
        if match:
            return match, year_label
        checked.append(f"{year_label}: {', '.join(names[:12]) or '업체 폴더 없음'}")
    raise RequiredFileMissingError(f"2025·2024·2023 수입 폴더에서 업체를 찾지 못했습니다: {supplier}. 확인 결과: {' / '.join(checked)}")


def find_shipping_folder(drive: GoogleDriveService, supplier: DriveFile) -> DriveFile:
    names = ["shipping document", "shipping documents", "shipping_document", "shippingdocument", "선적서류", "무역서류"]
    item = match_folder(drive.list_children(supplier.id), names) or match_folder(drive.walk(supplier.id, max_depth=2, max_items=500), names)
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
    raise RequiredFileMissingError(f"{shipping.name} 안에서 Container {number} 폴더를 찾지 못했습니다. 확인된 폴더: {', '.join(item.name for item in folders[:25])}")


def find_documents(drive: GoogleDriveService, container: DriveFile) -> tuple[DriveFile, DriveFile]:
    items = drive.list_children(container.id)
    invoices = sorted([item for item in items if is_invoice(item)], key=lambda item: (0 if "_invoice_" in item.name.lower() else 1, item.name.lower()))
    quarantines = sorted([item for item in items if is_quarantine(item)], key=lambda item: (0 if "phyto" in item.name.lower() else 1, item.name.lower()))
    if not invoices or not quarantines:
        sub = drive.walk(container.id, max_depth=2, max_items=300)
        invoices = invoices or sorted([item for item in sub if is_invoice(item)], key=lambda item: item.name.lower())
        quarantines = quarantines or sorted([item for item in sub if is_quarantine(item)], key=lambda item: item.name.lower())
    if not invoices:
        raise RequiredFileMissingError(f"{container.name} 안에서 일반 Invoice 파일을 찾지 못했습니다.")
    if not quarantines:
        raise RequiredFileMissingError(f"{container.name} 안에서 Phyto 또는 검역파일을 찾지 못했습니다.")
    return invoices[0], quarantines[0]


def manual_file(draft_data: dict, role: str) -> tuple[bytes | None, str]:
    upload_id = str((((draft_data.get("manual_files") or {}).get(role) or {}).get("upload_id")) or "").strip()
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


def collect_drive_assets(variety_name: str, draft_data: dict) -> DriveAssets:
    settings = get_settings()
    result = DriveAssets()
    manual_invoice, manual_invoice_name = manual_file(draft_data, "invoice")
    manual_quarantine, manual_quarantine_name = manual_file(draft_data, "quarantine")

    try:
        drive = GoogleDriveService()
        match = find_variety_in_workbook(drive.download(settings.shipment_overview_file_id), variety_name)
        result.shipment, result.shipment_sheet, result.shipment_row = match.shipment, match.sheet_name, match.row_number
        result.supplier_name, number = split_shipment(result.shipment)
        supplier, result.import_year = find_supplier_across_import_folders(
            drive,
            result.supplier_name,
            [("2025 수입", settings.import_2025_folder_id), ("2024 수입", settings.import_2024_folder_id), ("2023 수입", settings.import_2023_folder_id)],
        )
        result.supplier_folder = supplier.name
        shipping = find_shipping_folder(drive, supplier)
        result.shipping_folder = shipping.name
        container = find_container_folder(drive, shipping, number)
        result.container_folder = container.name
        try:
            invoice, quarantine = find_documents(drive, container)
            result.invoice_name, result.quarantine_name = invoice.name, quarantine.name
            result.invoice_output, result.invoice_zip_name = process_invoice(invoice, drive.download(invoice.id), variety_name, result.shipment, match.values)
            result.quarantine_data = drive.download(quarantine.id)
            result.quarantine_number = quarantine_number_from_name(quarantine.name)
        except (RequiredFileMissingError, DriveOperationError) as exc:
            result.warnings.append(f"Drive 첨부서류 자동수집 미완료: {exc}")
    except Exception as exc:
        result.warnings.append(f"Drive 자료 자동검색 미완료: {exc}")

    if manual_invoice:
        result.invoice_output, result.invoice_name = manual_invoice, manual_invoice_name
        result.invoice_zip_name = f"06_{safe(manual_invoice_name)}"
        result.warnings.append("직접 업로드한 Invoice를 사용했습니다.")
    elif not result.invoice_output:
        result.warnings.append("Invoice가 첨부되지 않았습니다. 필요하면 사이트에서 직접 업로드하세요.")

    if manual_quarantine:
        result.quarantine_data, result.quarantine_name = manual_quarantine, manual_quarantine_name
        result.quarantine_number = quarantine_number_from_name(manual_quarantine_name)
        result.warnings.append("직접 업로드한 검역·Phyto 파일을 사용했습니다.")
    elif not result.quarantine_data:
        result.warnings.append("검역합격증 또는 Phyto가 첨부되지 않았습니다. 필요하면 사이트에서 직접 업로드하세요.")
    return result
