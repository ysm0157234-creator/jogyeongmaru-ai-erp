from __future__ import annotations

import io
import json
import re
import time
import zipfile

from datetime import datetime
from urllib.error import HTTPError, URLError
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
from app.services.report_generator import (
    build_breeding_document,
    build_characteristics_document,
    build_main_report,
    build_pdf_summary,
    build_sample_pledge_document,
)
from app.services.shipment_parser import (
    ShipmentMatch,
    find_variety_in_workbook,
)


class RequiredFileMissingError(RuntimeError):
    pass


DOCUMENT_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
]


# 같은 요청 안에서 같은 사진을 여러 번 받지 않도록 저장
IMAGE_CACHE: dict[str, bytes] = {}


def norm(value) -> str:
    return re.sub(
        r"[^a-z0-9가-힣]+",
        "",
        str(value or "").lower(),
    )


def safe(value) -> str:
    return re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        str(value),
    ).strip()


def folder(item: DriveFile) -> bool:
    return item.mime_type == FOLDER_MIME


def is_invoice(item: DriveFile) -> bool:
    name = item.name.lower()

    return (
        not folder(item)
        and name.endswith((".xlsx", ".xlsm", ".pdf"))
        and (
            "invoice" in name
            or "인보이스" in name
        )
        and "freight invoice" not in name
        and "freight_invoice" not in name
    )


def is_quarantine(item: DriveFile) -> bool:
    name = item.name.lower()

    return (
        not folder(item)
        and name.endswith(
            (
                ".pdf",
                ".jpg",
                ".jpeg",
                ".png",
            )
        )
        and any(
            keyword in name
            for keyword in (
                "검역",
                "quarantine",
                "phytosanitary",
                "phyto",
            )
        )
    )


def split_shipment(shipment: str) -> tuple[str, int]:
    """
    예시

    GreenSeasons07
    → GreenSeasons / 7

    GreenSeasons_07
    → GreenSeasons / 7
    """

    value = str(shipment or "").strip()

    match = re.match(
        r"^(.*?)[\s_-]*0*(\d+)$",
        value,
    )

    if not match:
        raise RequiredFileMissingError(
            "Shipment 값에서 업체명과 컨테이너 번호를 "
            f"분리할 수 없습니다: {shipment}"
        )

    supplier = match.group(1).strip(" _-")
    container_number = int(match.group(2))

    if not supplier:
        raise RequiredFileMissingError(
            f"Shipment 값에 업체명이 없습니다: {shipment}"
        )

    return supplier, container_number


def match_folder(
    items: list[DriveFile],
    names: list[str],
) -> DriveFile | None:
    folders = [
        item
        for item in items
        if folder(item)
    ]

    targets = [
        norm(name)
        for name in names
        if name
    ]

    # 정확한 이름 우선
    for item in folders:
        if norm(item.name) in targets:
            return item

    # 일부 이름 일치
    for item in folders:
        item_name = norm(item.name)

        if any(
            target
            and (
                target in item_name
                or item_name in target
            )
            for target in targets
        ):
            return item

    return None


def supplier_folder(
    drive: GoogleDriveService,
    root_id: str,
    supplier: str,
) -> DriveFile:
    names = [
        f"{supplier}_네덜란드",
        f"{supplier} 네덜란드",
        supplier,
    ]

    # 2025 수입 바로 아래에서 검색
    item = match_folder(
        drive.list_children(root_id),
        names,
    )

    if item:
        return item

    # 바로 아래에 없을 때만 제한적으로 검색
    item = match_folder(
        drive.walk(
            root_id,
            max_depth=2,
            max_items=1000,
        ),
        names,
    )

    if not item:
        raise RequiredFileMissingError(
            "2025 수입에서 업체 폴더를 찾지 못했습니다: "
            f"{supplier}_네덜란드"
        )

    return item


def shipping_folder(
    drive: GoogleDriveService,
    supplier: DriveFile,
) -> DriveFile:
    names = [
        "shipping document",
        "shipping documents",
        "shipping_document",
        "shippingdocument",
        "선적서류",
        "무역서류",
    ]

    item = match_folder(
        drive.list_children(supplier.id),
        names,
    )

    if item:
        return item

    item = match_folder(
        drive.walk(
            supplier.id,
            max_depth=2,
            max_items=500,
        ),
        names,
    )

    if not item:
        raise RequiredFileMissingError(
            f"{supplier.name} 안에서 "
            "shipping document 폴더를 찾지 못했습니다."
        )

    return item


def container_numbers_from_name(name: str) -> set[int]:
    """
    실제 폴더명 예시

    251212_container 7_MAEU262944634
    251208_container 3,5_COSU6437694570
    251222_container 9,10_MAEU263223238
    """

    value = str(name or "")

    match = re.search(
        r"(?i)container[\s_-]*([0-9,\s]+)",
        value,
    )

    if not match:
        return set()

    return {
        int(number)
        for number in re.findall(
            r"\d+",
            match.group(1),
        )
    }


def container_folder(
    drive: GoogleDriveService,
    shipping: DriveFile,
    number: int,
) -> DriveFile:
    children = drive.list_children(shipping.id)

    folders = [
        item
        for item in children
        if folder(item)
    ]

    # 실제 폴더명에서 컨테이너 번호 정확히 확인
    exact_matches = [
        item
        for item in folders
        if number in container_numbers_from_name(item.name)
    ]

    if exact_matches:
        return sorted(
            exact_matches,
            key=lambda item: item.name.lower(),
        )[0]

    # 단순 폴더명도 지원
    names = [
        f"Container {number}",
        f"Container{number}",
        f"Container_{number}",
        f"container {number}",
        f"container{number}",
    ]

    item = match_folder(
        folders,
        names,
    )

    if item:
        return item

    available = ", ".join(
        item.name
        for item in folders[:30]
    )

    raise RequiredFileMissingError(
        f"{shipping.name} 안에서 "
        f"Container {number} 폴더를 찾지 못했습니다. "
        f"확인된 폴더: {available}"
    )


def docs_in_container(
    drive: GoogleDriveService,
    container: DriveFile,
) -> tuple[DriveFile, DriveFile]:
    # 실제 구조상 Invoice와 Phyto가 컨테이너 폴더 바로 아래에 있음
    direct_items = drive.list_children(container.id)

    invoices = sorted(
        [
            item
            for item in direct_items
            if is_invoice(item)
        ],
        key=lambda item: (
            0
            if "_invoice_" in item.name.lower()
            else 1,
            item.name.lower(),
        ),
    )

    quarantines = sorted(
        [
            item
            for item in direct_items
            if is_quarantine(item)
        ],
        key=lambda item: (
            0
            if "phyto" in item.name.lower()
            else 1,
            item.name.lower(),
        ),
    )

    # 바로 아래에서 못 찾았을 때만 하위 폴더 확인
    if not invoices or not quarantines:
        sub_items = drive.walk(
            container.id,
            max_depth=2,
            max_items=300,
        )

        if not invoices:
            invoices = sorted(
                [
                    item
                    for item in sub_items
                    if is_invoice(item)
                ],
                key=lambda item: item.name.lower(),
            )

        if not quarantines:
            quarantines = sorted(
                [
                    item
                    for item in sub_items
                    if is_quarantine(item)
                ],
                key=lambda item: item.name.lower(),
            )

    if not invoices:
        raise RequiredFileMissingError(
            f"{container.name} 안에서 "
            "일반 Invoice 파일을 찾지 못했습니다."
        )

    if not quarantines:
        raise RequiredFileMissingError(
            f"{container.name} 안에서 "
            "Phyto 또는 검역파일을 찾지 못했습니다."
        )

    return invoices[0], quarantines[0]


def get_container_ancestor(
    drive: GoogleDriveService,
    item: DriveFile,
    root_folder_id: str,
    max_hops: int = 10,
) -> DriveFile | None:
    """
    검색된 인보이스의 부모 폴더를 거슬러 올라가
    Container 폴더를 찾는다.

    동시에 해당 파일이 2025 수입 폴더 아래에 있는지 확인한다.
    """

    current = item
    container = None

    for _ in range(max_hops):
        parents = current.parents or []

        if not parents:
            return None

        parent_id = parents[0]

        try:
            parent = drive.get_metadata(parent_id)
        except Exception:
            return None

        if "container" in norm(parent.name):
            container = parent

        if parent.id == root_folder_id:
            return container

        current = parent

    return None


def tulipa_invoice_candidates(
    drive: GoogleDriveService,
) -> list[DriveFile]:
    """
    2025 수입 전체 폴더를 직접 순회하지 않고,
    Google Drive 서버 검색으로 후보만 찾는다.
    """

    candidates: dict[str, DriveFile] = {}

    search_terms = [
        "Tulipa",
        "Tulip",
        "튤립",
    ]

    for term in search_terms:
        try:
            results = drive.search_files(
                term,
                name_only=False,
                mime_types=DOCUMENT_MIME_TYPES,
                limit=100,
            )

            for item in results:
                if is_invoice(item):
                    candidates[item.id] = item

        except Exception:
            continue

    for term in search_terms:
        try:
            results = drive.search_files(
                term,
                name_only=True,
                mime_types=DOCUMENT_MIME_TYPES,
                limit=100,
            )

            for item in results:
                if is_invoice(item):
                    candidates[item.id] = item

        except Exception:
            continue

    return sorted(
        candidates.values(),
        key=lambda item: item.name.lower(),
    )


def fallback_tulipa(
    drive: GoogleDriveService,
    root_id: str,
) -> tuple[DriveFile, DriveFile, DriveFile]:
    """
    Shipment Overview에 품종이 없을 때 사용.

    Drive 서버 검색에서 Tulipa 후보만 가져온 뒤,
    2025 수입 아래에 있는 인보이스만 확인한다.
    """

    candidates = tulipa_invoice_candidates(drive)

    if not candidates:
        raise RequiredFileMissingError(
            "Google Drive 검색에서 "
            "Tulipa가 포함된 인보이스 후보를 찾지 못했습니다."
        )

    for invoice in candidates[:50]:
        try:
            container = get_container_ancestor(
                drive,
                invoice,
                root_id,
            )

            if not container:
                continue

            container_items = drive.list_children(
                container.id
            )

            quarantine = next(
                (
                    item
                    for item in sorted(
                        container_items,
                        key=lambda value: value.name.lower(),
                    )
                    if is_quarantine(item)
                ),
                None,
            )

            if not quarantine:
                continue

            invoice_data = drive.download(
                invoice.id
            )

            if invoice.name.lower().endswith(
                (
                    ".xlsx",
                    ".xlsm",
                )
            ):
                contains_tulipa = workbook_contains(
                    invoice_data,
                    [
                        "Tulipa",
                        "Tulip",
                        "튤립",
                    ],
                )

            else:
                contains_tulipa = pdf_contains(
                    invoice_data,
                    [
                        "Tulipa",
                        "Tulip",
                        "튤립",
                    ],
                )

            if not contains_tulipa:
                continue

            return (
                container,
                invoice,
                quarantine,
            )

        except Exception:
            continue

    raise RequiredFileMissingError(
        "Shipment Overview에서 품종을 찾지 못했고, "
        "Drive 검색 후보 중에서도 2025 수입에 속한 "
        "Tulipa 인보이스와 검역파일을 찾지 못했습니다."
    )


def selected_image_candidate(
    data: dict,
    role: str,
) -> dict:
    selected_id = (
        data
        .get(
            "selected_images",
            {},
        )
        .get(role)
    )

    for image in data.get(
        "image_candidates",
        [],
    ):
        if image.get("id") == selected_id:
            return image

    label = (
        "전체 모습"
        if role == "overall"
        else "꽃 근접"
    )

    raise RequiredFileMissingError(
        f"{label} 사진이 선택되지 않았습니다."
    )


def image_urls_from_candidate(
    candidate: dict,
) -> list[str]:
    """
    사진 후보 안의 URL을 우선순위대로 모은다.

    같은 URL은 한 번만 사용한다.
    """

    possible_urls = [
        candidate.get("download_url"),
        candidate.get("preview_url"),
        candidate.get("backup_url"),
        candidate.get("backup_url_2"),
        candidate.get("image_url"),
    ]

    result = []

    for url in possible_urls:
        if (
            url
            and url not in result
        ):
            result.append(url)

    if not result:
        raise RequiredFileMissingError(
            f"사진 후보에 사용할 URL이 없습니다: "
            f"{candidate.get('title', '제목 없음')}"
        )

    return result


def image_referer(url: str) -> str:
    lower = url.lower()

    if (
        "wikimedia.org" in lower
        or "wikipedia.org" in lower
    ):
        return "https://commons.wikimedia.org/"

    if "rhs.org.uk" in lower:
        return "https://www.rhs.org.uk/"

    return "https://www.google.com/"


def download_single_image(
    url: str,
    max_attempts: int = 5,
) -> bytes:
    """
    사진 한 URL 다운로드.

    HTTP 429 발생 시 대기시간을 늘리며 재시도한다.
    """

    if url in IMAGE_CACHE:
        return IMAGE_CACHE[url]

    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 "
                        "(Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 "
                        "(KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    ),
                    "Accept": (
                        "image/avif,image/webp,"
                        "image/apng,image/svg+xml,"
                        "image/*,*/*;q=0.8"
                    ),
                    "Accept-Language": (
                        "ko-KR,ko;q=0.9,"
                        "en-US;q=0.8,en;q=0.7"
                    ),
                    "Referer": image_referer(url),
                    "Cache-Control": "no-cache",
                },
            )

            with urlopen(
                request,
                timeout=60,
            ) as response:
                content_type = (
                    response
                    .headers
                    .get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )

                if not content_type.startswith(
                    "image/"
                ):
                    raise RequiredFileMissingError(
                        "사진 URL이 이미지 형식이 아닙니다. "
                        f"Content-Type: {content_type}"
                    )

                image_data = response.read(
                    15 * 1024 * 1024
                )

                if len(image_data) < 1000:
                    raise RequiredFileMissingError(
                        "사진 데이터가 너무 작습니다."
                    )

                IMAGE_CACHE[url] = image_data

                return image_data

        except HTTPError as error:
            last_error = error

            if error.code == 429:
                # 429는 요청 제한이므로 점점 오래 기다림
                wait_seconds = 5 * (attempt + 1)

                retry_after = error.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        wait_seconds = max(
                            wait_seconds,
                            int(retry_after),
                        )
                    except ValueError:
                        pass

                time.sleep(wait_seconds)
                continue

            if error.code in (
                403,
                408,
                500,
                502,
                503,
                504,
            ):
                time.sleep(
                    3 * (attempt + 1)
                )
                continue

            break

        except (
            URLError,
            TimeoutError,
            ConnectionError,
        ) as error:
            last_error = error

            time.sleep(
                3 * (attempt + 1)
            )
            continue

        except RequiredFileMissingError as error:
            last_error = error
            break

        except Exception as error:
            last_error = error

            time.sleep(
                2 * (attempt + 1)
            )
            continue

    raise RequiredFileMissingError(
        f"사진 URL 다운로드 실패: {url} / {last_error}"
    )


def download_image_candidates(
    urls: list[str],
) -> bytes:
    """
    첫 URL이 실패하면 다음 URL로 넘어간다.
    """

    last_error: Exception | None = None

    for url in urls:
        try:
            return download_single_image(url)

        except Exception as error:
            last_error = error
            continue

    raise RequiredFileMissingError(
        "모든 사진 URL 후보 다운로드에 실패했습니다: "
        f"{last_error}"
    )


def process_invoice(
    invoice_file: DriveFile,
    invoice_data: bytes,
    variety: str,
    shipment: str,
    values: dict,
) -> tuple[bytes, str]:
    try:
        if invoice_file.name.lower().endswith(
            (
                ".xlsx",
                ".xlsm",
            )
        ):
            return (
                filter_invoice_xlsx(
                    invoice_data,
                    variety,
                    shipment,
                ),
                (
                    f"06_{safe(variety)}"
                    "_신고용_invoice.xlsx"
                ),
            )

        if invoice_file.name.lower().endswith(
            ".pdf"
        ):
            output, _ = extract_invoice_pdf_pages(
                invoice_data,
                variety,
            )

            return (
                output,
                (
                    f"06_{safe(variety)}"
                    "_신고용_invoice.pdf"
                ),
            )

    except Exception:
        pass

    return (
        create_invoice_extract_xlsx(
            variety,
            shipment,
            values,
            invoice_file.name,
        ),
        (
            f"06_{safe(variety)}"
            "_신고용_invoice_발췌.xlsx"
        ),
    )


def run_workflow(
    variety_name: str,
    draft_data: dict,
) -> tuple[bytes, dict]:
    settings = get_settings()
    drive = GoogleDriveService()

    search_log = []

    supplier = None
    shipping = None

    shipment_bytes = drive.download(
        settings.shipment_overview_file_id
    )

    try:
        match = find_variety_in_workbook(
            shipment_bytes,
            variety_name,
        )

        supplier_name, container_number = split_shipment(
            match.shipment
        )

        supplier = supplier_folder(
            drive,
            settings.import_2025_folder_id,
            supplier_name,
        )

        shipping = shipping_folder(
            drive,
            supplier,
        )

        container = container_folder(
            drive,
            shipping,
            container_number,
        )

        invoice, quarantine = docs_in_container(
            drive,
            container,
        )

        search_log.extend(
            [
                f"H열 Shipment: {match.shipment}",
                f"업체 폴더: {supplier.name}",
                f"Shipping document: {shipping.name}",
                f"Container: {container.name}",
                f"Invoice: {invoice.name}",
                f"Phyto/검역: {quarantine.name}",
            ]
        )

        search_mode = (
            "shipment_overview_2025_route"
        )

    except LookupError:
        (
            container,
            invoice,
            quarantine,
        ) = fallback_tulipa(
            drive,
            settings.import_2025_folder_id,
        )

        match = ShipmentMatch(
            sheet_name=(
                "2025 수입 Tulipa 보조검색"
            ),
            row_number=0,
            description=variety_name,
            shipment=container.name,
            values={
                "품종명": variety_name,
                "검색 방식": (
                    "Drive 서버 검색으로 "
                    "Tulipa 인보이스 후보 확인"
                ),
            },
            source=(
                "import_2025_tulipa_fallback"
            ),
        )

        search_mode = (
            "import_2025_tulipa_fallback"
        )

        search_log.extend(
            [
                (
                    "Shipment Overview 미발견"
                ),
                (
                    "Tulipa 인보이스 Container 사용: "
                    f"{container.name}"
                ),
                f"Invoice: {invoice.name}",
                f"Phyto/검역: {quarantine.name}",
            ]
        )

    invoice_data = drive.download(
        invoice.id
    )

    quarantine_data = drive.download(
        quarantine.id
    )

    overall_candidate = selected_image_candidate(
        draft_data,
        "overall",
    )

    closeup_candidate = selected_image_candidate(
        draft_data,
        "closeup",
    )

    overall_urls = image_urls_from_candidate(
        overall_candidate
    )

    closeup_urls = image_urls_from_candidate(
        closeup_candidate
    )

    if set(overall_urls) == set(closeup_urls):
        raise RequiredFileMissingError(
            "전체 모습과 꽃 근접 사진은 "
            "서로 다른 사진이어야 합니다."
        )

    overall_image = download_image_candidates(
        overall_urls
    )

    # 같은 서버를 연속 호출하지 않도록 약간 대기
    time.sleep(2)

    closeup_image = download_image_candidates(
        closeup_urls
    )

    final_name = draft_data.get(
        "matched_name",
        variety_name,
    )

    korean_name = draft_data.get(
        "korean_name",
        "튤립 썬러버",
    )

    scientific_name = draft_data.get(
        "scientific_name",
        "Tulipa 'Sun Lover'",
    )

    characteristics = draft_data.get(
        "characteristics_draft",
        "",
    )

    breeding_process = draft_data.get(
        "breeding_process_draft",
        "",
    )

    if not characteristics.strip():
        raise RequiredFileMissingError(
            "품종 특성 설명이 비어 있습니다."
        )

    if not breeding_process.strip():
        raise RequiredFileMissingError(
            "품종 육성과정이 비어 있습니다."
        )

    invoice_output, invoice_name = process_invoice(
        invoice,
        invoice_data,
        variety_name,
        match.shipment,
        match.values,
    )

    main_document = build_main_report(
        final_name,
        korean_name,
        scientific_name,
        match.shipment,
        characteristics,
        breeding_process,
        overall_image,
        closeup_image,
    )

    characteristics_document = (
        build_characteristics_document(
            final_name,
            korean_name,
            scientific_name,
            characteristics,
            overall_image,
            closeup_image,
        )
    )

    breeding_document = build_breeding_document(
        final_name,
        korean_name,
        breeding_process,
    )

    pledge_document = build_sample_pledge_document(
        final_name,
        korean_name,
    )

    summary_pdf = build_pdf_summary(
        final_name,
        scientific_name,
        match.shipment,
        invoice.name,
        quarantine.name,
    )

    manifest = {
        "generated_at": (
            datetime.utcnow().isoformat()
            + "Z"
        ),
        "variety": variety_name,
        "search_mode": search_mode,
        "shipment": match.shipment,
        "supplier_folder": (
            supplier.name
            if supplier
            else None
        ),
        "shipping_folder": (
            shipping.name
            if shipping
            else None
        ),
        "container_folder": container.name,
        "invoice": invoice.name,
        "quarantine": quarantine.name,
        "photos": {
            "overall": {
                "title": overall_candidate.get(
                    "title"
                ),
                "urls": overall_urls,
            },
            "closeup": {
                "title": closeup_candidate.get(
                    "title"
                ),
                "urls": closeup_urls,
            },
        },
        "search_log": search_log,
    }

    output = io.BytesIO()
    base = safe(variety_name)

    with zipfile.ZipFile(
        output,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            (
                f"{base}/"
                "01_생산수입판매신고서_검토안.docx"
            ),
            main_document,
        )

        archive.writestr(
            (
                f"{base}/"
                "02_품종특성설명.docx"
            ),
            characteristics_document,
        )

        archive.writestr(
            (
                f"{base}/"
                "03_품종육성과정.docx"
            ),
            breeding_document,
        )

        archive.writestr(
            (
                f"{base}/"
                "04_시료제출확약서.docx"
            ),
            pledge_document,
        )

        archive.writestr(
            (
                f"{base}/05_"
                f"{safe(quarantine.name)}"
            ),
            quarantine_data,
        )

        archive.writestr(
            f"{base}/{invoice_name}",
            invoice_output,
        )

        archive.writestr(
            (
                f"{base}/"
                "07_품종전체사진.jpg"
            ),
            overall_image,
        )

        archive.writestr(
            (
                f"{base}/"
                "08_꽃근접사진.jpg"
            ),
            closeup_image,
        )

        archive.writestr(
            (
                f"{base}/"
                "09_처리요약.pdf"
            ),
            summary_pdf,
        )

        archive.writestr(
            (
                f"{base}/"
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
