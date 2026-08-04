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


def norm(value):
    return re.sub(
        r"[^a-z0-9가-힣]+",
        "",
        str(value or "").lower(),
    )


def safe(value):
    return re.sub(
        r'[\\/:*?"<>|]+',
        "_",
        str(value),
    ).strip()


def folder(item):
    return item.mime_type == FOLDER_MIME


def is_invoice(item):
    name = item.name.lower()

    return (
        not folder(item)
        and name.endswith((".xlsx", ".xlsm", ".pdf"))
        and (
            "invoice" in name
            or "인보이스" in name
        )
    )


def is_quarantine(item):
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


def split_shipment(shipment):
    """
    GreenSeasons07
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


def match_folder(items, names):
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

    # 정확히 일치하는 폴더 우선
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
    drive,
    root_id,
    supplier,
):
    names = [
        f"{supplier}_네덜란드",
        f"{supplier} 네덜란드",
        supplier,
    ]

    # 2025수입 바로 아래에서 먼저 검색
    item = match_folder(
        drive.list_children(root_id),
        names,
    )

    if item:
        return item

    # 바로 아래에 없을 때만 2단계 제한 검색
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
    drive,
    supplier,
):
    names = [
        "Shipping document",
        "Shipping documents",
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
            "Shipping document 폴더를 찾지 못했습니다."
        )

    return item


def container_folder(
    drive,
    shipping,
    number,
):
    children = drive.list_children(
        shipping.id
    )

    names = [
        f"Container {number}",
        f"Container{number}",
        f"Container_{number}",
        f"container {number}",
        f"container{number}",
        str(number),
    ]

    item = match_folder(
        children,
        names,
    )

    if item:
        return item

    number_text = str(number)

    for child in children:
        if not folder(child):
            continue

        child_name = norm(child.name)

        if (
            "container" in child_name
            and number_text in child_name
        ):
            return child

    raise RequiredFileMissingError(
        f"{shipping.name} 안에서 "
        f"Container {number} 폴더를 찾지 못했습니다."
    )


def docs_in_container(
    drive,
    container,
):
    # Container 폴더 내부만 제한적으로 확인
    items = drive.walk(
        container.id,
        max_depth=3,
        max_items=500,
    )

    invoices = sorted(
        [
            item
            for item in items
            if is_invoice(item)
        ],
        key=lambda item: item.name.lower(),
    )

    quarantines = sorted(
        [
            item
            for item in items
            if is_quarantine(item)
        ],
        key=lambda item: item.name.lower(),
    )

    invoice = (
        invoices[0]
        if invoices
        else None
    )

    quarantine = (
        quarantines[0]
        if quarantines
        else None
    )

    if not invoice:
        raise RequiredFileMissingError(
            f"{container.name} 안에서 "
            "인보이스를 찾지 못했습니다."
        )

    if not quarantine:
        raise RequiredFileMissingError(
            f"{container.name} 안에서 "
            "검역합격증 또는 Phyto 파일을 찾지 못했습니다."
        )

    return invoice, quarantine


def get_container_ancestor(
    drive,
    item,
    root_folder_id,
    max_hops=10,
):
    """
    검색된 인보이스의 상위 폴더를 거슬러 올라가
    Container 폴더를 찾는다.

    동시에 2025수입 폴더 안에 있는 파일인지 확인한다.
    """

    current = item
    container = None

    for _ in range(max_hops):
        parents = current.parents or []

        if not parents:
            return None

        parent_id = parents[0]

        try:
            parent = drive.get_metadata(
                parent_id
            )
        except Exception:
            return None

        if (
            "container"
            in norm(parent.name)
        ):
            container = parent

        if parent.id == root_folder_id:
            return container

        current = parent

    return None


def tulipa_invoice_candidates(
    drive,
):
    """
    Drive 전체 폴더를 직접 순회하지 않고
    Google Drive 서버 검색으로 Tulipa 후보만 가져온다.
    """

    candidates = {}

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

    # 파일명이 Tulipa인 경우도 검색
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
    drive,
    root_id,
):
    """
    Shipment Overview에 품종이 없을 때 실행한다.

    기존:
    2025수입 전체 4,000개 순회
    → 인보이스를 하나씩 다운로드

    수정:
    Drive 서버에서 Tulipa 포함 인보이스 후보만 검색
    → 후보의 Container 폴더만 확인
    """

    candidates = tulipa_invoice_candidates(
        drive
    )

    if not candidates:
        raise RequiredFileMissingError(
            "Google Drive 서버 검색에서 "
            "Tulipa가 포함된 인보이스 후보를 찾지 못했습니다."
        )

    for invoice in candidates[:50]:
        try:
            # 검색 결과가 실제로 2025수입 아래에 있는지 확인
            container = get_container_ancestor(
                drive,
                invoice,
                root_id,
            )

            if not container:
                continue

            # Container 내부에서 Invoice와 검역파일 확인
            container_items = drive.walk(
                container.id,
                max_depth=3,
                max_items=500,
            )

            quarantine = next(
                (
                    item
                    for item in sorted(
                        container_items,
                        key=lambda value: (
                            value.name.lower()
                        ),
                    )
                    if is_quarantine(item)
                ),
                None,
            )

            if not quarantine:
                continue

            # 검색된 인보이스 내용 재확인
            invoice_data = drive.download(
                invoice.id
            )

            if invoice.name.lower().endswith(
                (
                    ".xlsx",
                    ".xlsm",
                )
            ):
                contains_tulipa = (
                    workbook_contains(
                        invoice_data,
                        [
                            "Tulipa",
                            "Tulip",
                            "튤립",
                        ],
                    )
                )
            else:
                contains_tulipa = (
                    pdf_contains(
                        invoice_data,
                        [
                            "Tulipa",
                            "Tulip",
                            "튤립",
                        ],
                    )
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
        "Drive 검색 후보 중에서도 2025수입에 속한 "
        "Tulipa 인보이스와 검역파일을 찾지 못했습니다."
    )


def image_url(
    data,
    role,
):
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
        if (
            image.get("id")
            == selected_id
        ):
            return (
                image.get("download_url")
                or image.get("preview_url")
                or ""
            )

    label = (
        "전체 모습"
        if role == "overall"
        else "꽃 근접"
    )

    raise RequiredFileMissingError(
        f"{label} 사진이 선택되지 않았습니다."
    )


def download_image(url):
    try:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "Jogyeongmaru-AI-ERP/6.1"
                ),
                "Accept": "image/*",
            },
        )

        with urlopen(
            request,
            timeout=40,
        ) as response:
            content_type = (
                response
                .headers
                .get(
                    "Content-Type",
                    "",
                )
            )

            if not content_type.startswith(
                "image/"
            ):
                raise RequiredFileMissingError(
                    "사진 URL이 이미지가 아닙니다."
                )

            image_data = response.read(
                15 * 1024 * 1024
            )

            if len(image_data) < 1000:
                raise RequiredFileMissingError(
                    "사진 데이터가 너무 작습니다."
                )

            return image_data

    except RequiredFileMissingError:
        raise

    except Exception as error:
        raise RequiredFileMissingError(
            "사진을 내려받지 못했습니다: "
            f"{error}"
        ) from error


def process_invoice(
    invoice_file,
    invoice_data,
    variety,
    shipment,
    values,
):
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
            output, _ = (
                extract_invoice_pdf_pages(
                    invoice_data,
                    variety,
                )
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
    variety_name,
    draft_data,
):
    settings = get_settings()
    drive = GoogleDriveService()

    log = []
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

        supplier_name, container_number = (
            split_shipment(
                match.shipment
            )
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

        invoice, quarantine = (
            docs_in_container(
                drive,
                container,
            )
        )

        log.extend(
            [
                (
                    f"H열 Shipment: "
                    f"{match.shipment}"
                ),
                (
                    f"업체 폴더: "
                    f"{supplier.name}"
                ),
                (
                    "Shipping document: "
                    f"{shipping.name}"
                ),
                (
                    f"Container: "
                    f"{container.name}"
                ),
            ]
        )

        mode = (
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

        mode = (
            "import_2025_tulipa_fallback"
        )

        log.append(
            "Tulipa 인보이스 Container 사용: "
            f"{container.name}"
        )

    invoice_data = drive.download(
        invoice.id
    )

    quarantine_data = drive.download(
        quarantine.id
    )

    overall_url = image_url(
        draft_data,
        "overall",
    )

    closeup_url = image_url(
        draft_data,
        "closeup",
    )

    if overall_url == closeup_url:
        raise RequiredFileMissingError(
            "전체 모습과 꽃 근접 사진은 "
            "서로 달라야 합니다."
        )

    overall_image = download_image(
        overall_url
    )

    closeup_image = download_image(
        closeup_url
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

    invoice_output, invoice_name = (
        process_invoice(
            invoice,
            invoice_data,
            variety_name,
            match.shipment,
            match.values,
        )
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

    breeding_document = (
        build_breeding_document(
            final_name,
            korean_name,
            breeding_process,
        )
    )

    pledge_document = (
        build_sample_pledge_document(
            final_name,
            korean_name,
        )
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
        "search_mode": mode,
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
        "container_folder": (
            container.name
        ),
        "invoice": invoice.name,
        "quarantine": (
            quarantine.name
        ),
        "search_log": log,
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