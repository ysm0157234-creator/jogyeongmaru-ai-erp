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
from app.services.report_generator import build_pdf_summary
from app.services.hwp_template_service import HwpTemplateError, build_hwpx_report
from app.services.shipment_parser import find_variety_in_workbook


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


def find_supplier_folder(drive: GoogleDriveService, root_id: str, supplier: str) -> DriveFile:
    # 국가명, 법인 접미사, 공백·밑줄·대소문자가 달라도 같은 업체로 찾는다.
    candidates = [item for item in drive.list_children(root_id) if is_folder(item)]
    if not candidates:
        candidates = [
            item for item in drive.walk(root_id, max_depth=4, max_items=2500)
            if is_folder(item)
        ]

    ranked = sorted(
        ((_supplier_match_score(item.name, supplier), item) for item in candidates),
        key=lambda pair: (-pair[0], pair[1].name.lower()),
    )
    if ranked and ranked[0][0] >= 68.0:
        return ranked[0][1]

    checked = ", ".join(item.name for _, item in ranked[:20]) or "없음"
    raise RequiredFileMissingError(
        f"2025 수입에서 업체 폴더를 찾지 못했습니다: {supplier}. "
        f"확인한 폴더: {checked}"
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


def selected_candidate(data: dict, role: str) -> dict:
    selected_id = data.get("selected_images", {}).get(role)
    for item in data.get("image_candidates", []):
        if item.get("id") == selected_id:
            return item
    label = "전체 모습" if role == "overall" else "꽃 근접"
    raise RequiredFileMissingError(f"{label} 사진이 선택되지 않았습니다.")


def candidate_urls(candidate: dict) -> list[str]:
    output: list[str] = []
    for key in ("download_url", "preview_url", "backup_url", "backup_url_2", "image_url"):
        value = str(candidate.get(key) or "").strip()
        if value and value not in output:
            output.append(value)
    if not output:
        raise RequiredFileMissingError(f"사진 후보 URL이 없습니다: {candidate.get('title', '제목 없음')}")
    return output


def _normalize_image_to_jpeg(raw_data: bytes) -> bytes:
    if len(raw_data) < 500:
        raise RequiredFileMissingError("사진 데이터가 너무 작습니다.")

    head = raw_data[:200].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise RequiredFileMissingError(
            "사진 주소에서 이미지가 아니라 웹페이지가 반환되었습니다."
        )

    try:
        with Image.open(io.BytesIO(raw_data)) as image:
            image.load()

            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
            converted = output.getvalue()
    except UnidentifiedImageError as exc:
        raise RequiredFileMissingError(
            "다운로드한 파일을 이미지로 인식하지 못했습니다."
        ) from exc

    if len(converted) < 1000:
        raise RequiredFileMissingError("JPEG 변환 결과가 올바르지 않습니다.")
    return converted


def download_image(urls: list[str]) -> bytes:
    last_error: Exception | None = None

    for url in [item for item in urls if item]:
        for attempt in range(4):
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                        ),
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "Referer": "https://www.google.com/",
                    },
                )
                with urlopen(request, timeout=60) as response:
                    raw = response.read(20 * 1024 * 1024)
                return _normalize_image_to_jpeg(raw)
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    import time
                    time.sleep(2 * (attempt + 1))

    raise RequiredFileMissingError(
        f"모든 사진 후보 다운로드 또는 JPEG 변환에 실패했습니다: {last_error}"
    )


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
    drive = GoogleDriveService()
    shipment_bytes = drive.download(settings.shipment_overview_file_id)
    match = find_variety_in_workbook(shipment_bytes, variety_name)
    supplier_name, number = split_shipment(match.shipment)
    supplier = find_supplier_folder(drive, settings.import_2025_folder_id, supplier_name)
    shipping = find_shipping_folder(drive, supplier)
    container = find_container_folder(drive, shipping, number)
    invoice, quarantine = find_documents(drive, container)

    invoice_data = drive.download(invoice.id)
    quarantine_data = drive.download(quarantine.id)
    overall_candidate = selected_candidate(draft_data, "overall")
    closeup_candidate = selected_candidate(draft_data, "closeup")
    overall_image = download_image(candidate_urls(overall_candidate))
    time.sleep(1)
    closeup_image = download_image(candidate_urls(closeup_candidate))

    final_name = draft_data.get("matched_name") or variety_name
    korean_name = draft_data.get("korean_name") or ""
    scientific_name = draft_data.get("scientific_name") or variety_name
    characteristics = str(draft_data.get("characteristics_draft") or "").strip()
    breeding = str(draft_data.get("breeding_process_draft") or "").strip()
    if not characteristics or not breeding:
        raise RequiredFileMissingError("품종 특성 설명 또는 육성과정이 비어 있습니다.")

    invoice_output, invoice_name = process_invoice(
        invoice, invoice_data, variety_name, match.shipment, match.values
    )

    template_path = (
        Path(__file__).resolve().parent.parent
        / "templates"
        / "plant_import_report_template.hwpx"
    )
    now = datetime.now()
    report_date_spaced = f"{now.year}년     {now.month}월     {now.day}일"
    quarantine_number = quarantine_number_from_name(quarantine.name)

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
    except HwpTemplateError as exc:
        raise RequiredFileMissingError(f"한글 신고서 생성 실패: {exc}") from exc

    summary = build_pdf_summary(
        final_name, scientific_name, match.shipment, invoice.name, quarantine.name
    )

    manifest = {
        "build_version": "v17.1-strict-name-image-folder-fix",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variety": variety_name,
        "matched_name": final_name,
        "scientific_name": scientific_name,
        "shipment": match.shipment,
        "shipment_sheet": match.sheet_name,
        "shipment_row": match.row_number,
        "supplier_folder": supplier.name,
        "shipping_folder": shipping.name,
        "container_folder": container.name,
        "invoice": invoice.name,
        "quarantine": quarantine.name,
        "quarantine_number": quarantine_number,
        "report_format": "HWPX original template",
        "photos": {
            "overall": overall_candidate,
            "closeup": closeup_candidate,
        },
    }

    output = io.BytesIO()
    base = safe(variety_name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{base}/01_품종_생산수입판매_신고서_검토안.hwpx",
            hwpx_report,
        )
        archive.writestr(f"{base}/02_{safe(quarantine.name)}", quarantine_data)
        archive.writestr(f"{base}/{invoice_name}", invoice_output)
        archive.writestr(f"{base}/04_품종전체사진.jpg", overall_image)
        archive.writestr(f"{base}/05_꽃근접사진.jpg", closeup_image)
        archive.writestr(f"{base}/06_처리요약.pdf", summary)
        archive.writestr(
            f"{base}/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        )
    return output.getvalue(), manifest
