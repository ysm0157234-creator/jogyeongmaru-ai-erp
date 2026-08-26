from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from datetime import datetime, timezone

from app.services.document_manager import COMPANY, DocumentBundle
from app.services.past_filings import suggest_crop_korean, suggest_cultivar_korean
from app.services.plant_research_service import BUILD_VERSION
from app.services.drive_manager import DriveAssets


_HANGUL = re.compile(r"[가-힣]")


def korean_only(value: str) -> str:
    """한글이 없으면 빈 값으로 돌려준다.

    국립종자원 작물 등록부는 한글 일반명으로 찾는다. AI가 'Hydrangea' 같은 영문을
    돌려주면 검색이 어긋나므로, 차라리 비워서 사람이 고르게 한다.
    """
    text = str(value or "").strip()
    return text if _HANGUL.search(text) else ""


def derive_cultivar(draft_data: dict, scientific_name: str, fallback: str) -> str:
    """품종명만 뽑는다.

    조사 결과에 품종명이 따로 없으면 신고명에서 학명 부분을 걷어낸 나머지를 쓴다.
    (예: 'Hydrangea macrophylla Endless Summer' - 'Hydrangea macrophylla'
      -> 'Endless Summer')
    """
    cultivar = str(draft_data.get("cultivar") or "").strip()
    if cultivar:
        return cultivar

    name = str(fallback or "").strip()
    words = str(scientific_name or "").split()[:2]
    rest = name
    for word in words:
        rest = re.sub(rf"\b{re.escape(word)}\b", " ", rest, flags=re.I)
    rest = re.sub(r"\s+", " ", rest).strip(" '\"")
    return rest or name


# 국립종자원 수입국가 목록에 있는 이름으로 맞춰야 선택된다.
_COUNTRY_HINTS = (
    "네덜란드", "독일", "벨기에", "덴마크", "프랑스", "이탈리아", "스페인", "영국",
    "폴란드", "미국", "캐나다", "일본", "중국", "대만", "베트남", "태국",
    "뉴질랜드", "호주", "이스라엘", "케냐", "에콰도르", "콜롬비아", "칠레",
)


def country_from(*candidates: str) -> str:
    """공급사 폴더 이름 등에서 수입국가를 찾아낸다.

    공급사 폴더가 'GreenSeasons_네덜란드'처럼 국가를 달고 있어서, 조사 결과의
    기본값('해외 생산지')보다 정확하다. 그 값은 종자원 국가 목록에 없어
    선택되지 않는다.
    """
    for text in candidates:
        for country in _COUNTRY_HINTS:
            if country in str(text or ""):
                return country
    return ""


def full_botanical_name(scientific_name: str, cultivar: str) -> str:
    """원예 품종의 정식 표기를 만든다.

    품종은 학명 뒤에 작은따옴표로 붙이는 것이 국제 규약이다.
      Yucca filamentosa + Color Guard -> Yucca filamentosa 'Color Guard'
    신고서 세부학명 칸에는 이 형태로 적어야 어떤 품종인지 분명해진다.
    """
    base = " ".join(str(scientific_name or "").split())
    name = str(cultivar or "").strip().strip("'\"")
    if not base:
        return name
    if not name:
        return base
    if "'" in base:  # 이미 품종이 붙어 있다
        return base
    return f"{base} '{name.title() if name.islower() else name}'"


# 매 신고마다 똑같이 붙는 회사 서류. 파일이 있으면 ZIP에 담고 없으면 건너뛴다.
COMPANY_DOCUMENTS = {
    "종자업등록증.pdf": "07_종자업등록증.pdf",
    "시료제출확약서.pdf": "08_시료제출확약서.pdf",
}


def company_documents() -> dict[str, bytes]:
    folder = Path(__file__).resolve().parent.parent / "documents"
    found: dict[str, bytes] = {}
    for name, zip_name in COMPANY_DOCUMENTS.items():
        path = folder / name
        if path.exists():
            found[zip_name] = path.read_bytes()
    return found


def safe(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", str(value or "")).strip() or "report"


def build_manifest(variety_name: str, draft_data: dict, assets: DriveAssets, documents: DocumentBundle, warnings: list[str]) -> dict:
    final_name = draft_data.get("matched_name") or variety_name
    return {
        # 버전 문자열은 plant_research_service 한 곳에서만 관리한다.
        # (예전에 ai_reports.py가 따로 들고 있다가 실제 코드와 어긋난 적이 있다.)
        "build_version": BUILD_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "variety": variety_name,
        "matched_name": final_name,
        "scientific_name": str(draft_data.get("scientific_name") or variety_name),
        "shipment": assets.shipment,
        "shipment_sheet": assets.shipment_sheet,
        "shipment_row": assets.shipment_row,
        "import_year_folder": assets.import_year,
        "supplier_folder": assets.supplier_folder,
        "shipping_folder": assets.shipping_folder,
        "container_folder": assets.container_folder,
        "invoice": assets.invoice_name,
        "quarantine": assets.quarantine_name,
        "quarantine_number": assets.quarantine_number,
        "report_formats": ["HWP"] if documents.hwp else (["HWPX"] if documents.hwpx else ["DOCX"]),
        "warnings": warnings,
        # 국립종자원(seednet) 신고 자동입력이 그대로 쓰는 값. 서식 ①~⑨란과 1:1로 맞춘다.
        "report_fields": {
            "신고인_성명": COMPANY["representative"],
            "신고인_생년월일": COMPANY["birth_date"],
            "신고인_주소": COMPANY["address"],
            "신고인_법인명칭": COMPANY["company_name"],
            "신고인_전화번호": COMPANY["phone"],
            # 초안에 한글명이 없으면(예전 버전으로 조사했거나 AI가 영문을 준 경우)
            # 여기서 한 번 더 채운다. 초안을 다시 조사하지 않아도 되게 하려는 것이다.
            "작물_일반명": korean_only(draft_data.get("korean_name"))
            or suggest_crop_korean(draft_data.get("scientific_name", "")),
            # 작물 검색에 쓸 말. 한글 일반명이 있으면 그것으로, 없으면 학명으로 찾는다.
            # 종자원 작물검색은 속명으로도 결과를 준다(예: 'Hydrangea' -> 수국·미국수국·수국속).
            # 종소명까지 붙이면 결과가 안 나오므로 속명만 쓴다.
            "작물_검색어": (
                korean_only(draft_data.get("korean_name"))
                or suggest_crop_korean(draft_data.get("scientific_name", ""))
                or " ".join(str(draft_data.get("scientific_name") or "").split()[:2])
            ),
            # 종까지 넣어 찾으면 결과가 없을 때가 있어, 속명으로 한 번 더 찾는다.
            "작물_검색어_대체": next(
                iter(str(draft_data.get("scientific_name") or "").split()), ""
            ),
            "작물_학명": str(draft_data.get("scientific_name") or ""),
            # 세부학명 칸에 넣을 정식 표기. 품종명을 작은따옴표로 붙인다.
            "작물_학명_전체": full_botanical_name(
                draft_data.get("scientific_name", ""),
                derive_cultivar(draft_data, draft_data.get("scientific_name", ""), final_name),
            ),
            "품종_명칭": derive_cultivar(
                draft_data, draft_data.get("scientific_name", ""), final_name
            ),
            # 국립종자원은 품종명 한글 표기를 따로 받는다(예: PIIHQ-I → 피엘엘에이치큐-엘).
            # 규정상 사람이 정하는 이름이라 AI가 만들지 않고, 신고 화면에서 비면 직접 입력한다.
            "품종_한글명": str(draft_data.get("cultivar_ko") or "")
            or suggest_cultivar_korean(
                draft_data.get("scientific_name", ""),
                derive_cultivar(draft_data, draft_data.get("scientific_name", ""), final_name),
            ),
            "원산지": country_from(
                draft_data.get("origin"), assets.supplier_folder, assets.shipment
            )
            or str(draft_data.get("origin") or ""),
            "종자업_등록번호": COMPANY["seed_business_number"],
            # 검역합격증이 스캔 이미지라 번호를 읽어낼 수 없다. 사람이 넣은 값을 우선한다.
            "검역합격_발급번호": str(draft_data.get("quarantine_number") or "").strip()
            or assets.quarantine_number
            or "",
            "품종_특성설명": str(draft_data.get("characteristics_draft") or ""),
            "육성과정_설명": str(draft_data.get("breeding_process_draft") or ""),
        },
    }


def build_package(
    *,
    variety_name: str,
    assets: DriveAssets,
    documents: DocumentBundle,
    overall_image: bytes,
    closeup_image: bytes,
    manifest: dict,
) -> bytes:
    output = io.BytesIO()
    base = safe(variety_name)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        # 국립종자원 제출본은 한글 .hwp다. .hwp가 만들어졌으면 그것만 넣고,
        # 실패했을 때만 예비본 .hwpx를 대신 넣는다(워드는 제출 서식이 아니라 넣지 않는다).
        if documents.hwp:
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.hwp", documents.hwp)
        elif documents.hwpx:
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.hwpx", documents.hwpx)
        else:
            # 한글 형식이 둘 다 실패한 경우에만 최후 수단으로 워드를 넣는다.
            archive.writestr(f"{base}/01_품종_생산수입판매_신고서_검토안.docx", documents.docx)
        if assets.quarantine_data:
            archive.writestr(f"{base}/02_{safe(assets.quarantine_name or '검역서류')}", assets.quarantine_data)
        if assets.invoice_output:
            archive.writestr(f"{base}/{assets.invoice_zip_name or '03_신고용_invoice.bin'}", assets.invoice_output)
        archive.writestr(f"{base}/04_품종전체사진.jpg", overall_image)
        archive.writestr(f"{base}/05_꽃근접사진.jpg", closeup_image)
        archive.writestr(f"{base}/06_처리요약.pdf", documents.summary_pdf)
        for zip_name, data in company_documents().items():
            archive.writestr(f"{base}/{zip_name}", data)
        archive.writestr(f"{base}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return output.getvalue()
