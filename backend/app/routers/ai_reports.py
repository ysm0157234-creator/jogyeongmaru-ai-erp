from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import io

from app.core.database import get_db
from app.models.ai_draft import AIDraft
from app.models.user import User
from app.schemas.ai_draft import (
    AIGenerateRequest,
    AIFileGenerateRequest,
    AIDraftUpdateRequest,
    AIDraftResponse,
)
from app.services.drive_service import DriveNotConfiguredError
from app.services.workflow import (
    RequiredFileMissingError,
    run_workflow,
)
from .deps import get_current_user

router = APIRouter(prefix="/api/ai-reports", tags=["ai-reports"])

SUNLOVER_RESULT = {
    "matched_name": "Tulipa spp. Sunlover",
    "korean_name": "튤립 썬러버",
    "scientific_name": "Tulipa 'Sun Lover'",
    "genus": "Tulipa",
    "cultivar": "Sun Lover",
    "agency_recommendation": "국립종자원",
    "match_confidence": 98,
    "classification": {
        "plant_type": "구근류",
        "horticultural_group": "Double Late Group",
        "flowering_period": "늦봄",
        "flower_color": "황금빛 노랑에서 주황·적색으로 변화",
        "height": "약 40~55cm",
        "use": "화단, 컨테이너, 절화",
    },
    "characteristics_draft": (
        "겹꽃형 튤립 품종으로, 개화 초기에는 황금빛 노란색을 띠며 "
        "적황색 줄무늬가 나타난다. 개화가 진행되면서 주황색에서 "
        "주황빛 적색으로 색상이 변화한다. 꽃은 크고 풍성한 겹꽃 형태이며 "
        "늦봄에 개화한다."
    ),
    "breeding_process_draft": (
        "해외 육종·생산업체에서 선발 및 증식된 영양번식성 구근 품종으로 "
        "동일 품종의 구근을 수입하여 국내에서 판매하는 품종이다. "
        "육성자 및 최초 선발연도는 공급사 증빙자료 확인 후 최종 기재한다."
    ),
    "shipment_match": {
        "status": "추가 확인 필요",
        "message": (
            "지정한 260114 Shipment overview에서는 Sunlover 행을 찾지 못했습니다. "
            "Drive 검색에서 250814_List_nyoung.xlsx, 250812_Tulipa.pdf 등 관련 파일이 확인되어 "
            "실제 운영 연결 시 이 파일들까지 순차 검색하도록 설계했습니다."
        ),
        "candidate_files": [
            {
                "title": "250814_List_nyoung.xlsx",
                "url": "https://drive.google.com/file/d/1Xj8w76SaZQg6nJKF-QucZN9OxObBSGmx",
                "purpose": "수입·품종 목록 후보",
            },
            {
                "title": "250812_Tulipa.pdf",
                "url": "https://drive.google.com/file/d/1ZOjcUgoMq84Eq9z3d_DjHXlKJAutKLCq",
                "purpose": "튤립 수입 증빙 후보",
            },
        ],
    },
    "drive_sources": [
        {
            "title": "114. Tulipa spp. Sunlover 튤립 썬러버_국립종자원",
            "url": "https://drive.google.com/drive/folders/1CrE3xCZz6Y_sj_9l3l6kJ2OFxLYspf-h",
            "type": "기존 완료 사례",
            "status": "확인됨",
        },
        {
            "title": "0. 업로드 완료_국립종자원",
            "url": "https://drive.google.com/drive/folders/12utpuVxYbC_FeJGewjfUGBR0RuL7rWO8",
            "type": "기준 폴더",
            "status": "확인됨",
        },
    ],
    "web_sources": [
        {
            "title": "RHS Plant Profile - Tulipa Sun Lover",
            "url": "https://www.rhs.org.uk/plants/315426/tulipa-sun-lover-%2811%29/details",
            "type": "공식 원예 데이터",
            "status": "검증됨",
        },
        {
            "title": "Jan de Wit en Zonen - Sun Lover",
            "url": "https://www.jandewitenzonen.com/en/assortment/tulip/501/Sun-Lover/",
            "type": "해외 공급사",
            "status": "검증됨",
        },
        {
            "title": "Tulips.com - Sunlover",
            "url": "https://www.tulips.com/product/sunlover/a-to-z-tulips",
            "type": "전문 공급사",
            "status": "참고",
        },
    ],
    "image_candidates": [
        {
            "id": "commons-01",
            "title": "Sunlover 전체 꽃 형태",
            "preview_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tulpe%20%27Sunlover%27%20im%20botanischen%20Garten%20in%20M%C3%BCnchen%2001.jpg?width=900",
            "source_url": "https://commons.wikimedia.org/wiki/File:Tulpe_%27Sunlover%27_im_botanischen_Garten_in_M%C3%BCnchen_01.jpg",
            "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tulpe%20%27Sunlover%27%20im%20botanischen%20Garten%20in%20M%C3%BCnchen%2001.jpg?width=1600",
            "source": "Wikimedia Commons",
            "license": "Commons 원본 페이지에서 라이선스 확인",
            "recommended": True,
            "role": "overall",
        },
        {
            "id": "commons-02",
            "title": "Sunlover 꽃 확대",
            "preview_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tulpe%20%27Sunlover%27%20im%20botanischen%20Garten%20in%20M%C3%BCnchen%2002.jpg?width=900",
            "source_url": "https://commons.wikimedia.org/wiki/File:Tulpe_%27Sunlover%27_im_botanischen_Garten_in_M%C3%BCnchen_02.jpg",
            "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tulpe%20%27Sunlover%27%20im%20botanischen%20Garten%20in%20M%C3%BCnchen%2002.jpg?width=1600",
            "source": "Wikimedia Commons",
            "license": "Commons 원본 페이지에서 라이선스 확인",
            "recommended": True,
            "role": "closeup",
            "role": "closeup",
        },
    ],
    "selected_images": {"overall": "commons-01", "closeup": "commons-02"},
    "selected_images": {"overall": "commons-01", "closeup": "commons-02"},
    "required_documents": [
        {"name": "품종의 특성 설명", "status": "초안 생성"},
        {"name": "품종의 육성과정", "status": "초안 생성"},
        {"name": "인보이스", "status": "Drive 후보 확인"},
        {"name": "검역합격증", "status": "Drive 추가 검색 필요"},
        {"name": "품종 사진 2장", "status": "후보 선택 가능"},
    ],
    "warnings": [
        "육성자·육성연도는 공급사 또는 권리자 자료로 최종 확인해야 합니다.",
        "260114 Shipment overview 파일에는 Sunlover가 확인되지 않아 수입수량과 규격은 다른 수입자료에서 찾아야 합니다.",
        "사진은 최종 제출 전에 해당 품종이 맞는지 사람이 확인해야 합니다.",
    ],
}

def normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def validate_trial_name(value: str) -> None:
    valid_names = {
        normalize_name("Tulipa spp. Sunlover"),
        normalize_name("Tulipa Sunlover"),
        normalize_name("Sunlover"),
        normalize_name("썬러버"),
        normalize_name("튤립 썬러버"),
    }
    if normalize_name(value) not in valid_names:
        raise HTTPException(
            status_code=404,
            detail="현재 시험 버전은 Tulipa spp. Sunlover만 처리할 수 있습니다.",
        )


@router.post("/generate", response_model=AIDraftResponse, status_code=201)
def generate_ai_report(
    payload: AIGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_trial_name(payload.variety_name)
    result = dict(SUNLOVER_RESULT)
    result["requested_agency"] = payload.agency

    draft = AIDraft(
        query_name=payload.variety_name,
        agency=payload.agency,
        status="검토 대기",
        result_data=result,
        created_by=current_user.id,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.put("/{draft_id}", response_model=AIDraftResponse)
def update_ai_draft(
    draft_id: int,
    payload: AIDraftUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    draft = db.get(AIDraft, draft_id)
    if not draft or draft.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="AI 신고 초안을 찾을 수 없습니다.")

    selected = payload.result_data.get("selected_images", {})
    if not selected.get("overall") or not selected.get("closeup"):
        raise HTTPException(
            status_code=422,
            detail="전체 모습 사진과 꽃 근접 사진을 각각 선택해야 합니다.",
        )
    if selected["overall"] == selected["closeup"]:
        raise HTTPException(
            status_code=422,
            detail="전체 모습과 꽃 근접 사진은 서로 달라야 합니다.",
        )

    draft.result_data = payload.result_data
    draft.status = payload.status
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("", response_model=list[AIDraftResponse])
def list_ai_drafts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(AIDraft).order_by(AIDraft.id.desc()).all()


@router.get("/drive/status")
def drive_status(_: User = Depends(get_current_user)):
    from app.core.config import get_settings

    settings = get_settings()

    has_json = bool(settings.google_service_account_json.strip())
    has_shipment = bool(settings.shipment_overview_file_id.strip())
    has_import_folder = bool(settings.import_2026_folder_id.strip())

    configured = has_json and has_shipment and has_import_folder

    missing = []
    if not has_json:
        missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not has_shipment:
        missing.append("SHIPMENT_OVERVIEW_FILE_ID")
    if not has_import_folder:
        missing.append("IMPORT_2026_FOLDER_ID")

    return {
        "configured": configured,
        "google_service_account_json": has_json,
        "shipment_overview_file_id": settings.shipment_overview_file_id,
        "import_2026_folder_id": settings.import_2026_folder_id,
        "missing_environment_variables": missing,
        "message": (
            "Google Drive 연결 준비 완료"
            if configured
            else "누락된 Render 환경변수: " + ", ".join(missing)
        ),
    }


@router.get("/{draft_id}", response_model=AIDraftResponse)
def get_ai_draft(
    draft_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    draft = db.get(AIDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="AI 신고 초안을 찾을 수 없습니다.")
    return draft


@router.post("/generate-files")
def generate_files(
    payload: AIFileGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    validate_trial_name(payload.variety_name)

    draft = db.get(AIDraft, payload.draft_id)
    if not draft or draft.created_by != current_user.id:
        raise HTTPException(status_code=404, detail="저장된 AI 신고 초안을 찾을 수 없습니다.")

    try:
        zip_bytes, _ = run_workflow(
            payload.variety_name,
            draft.result_data,
        )
    except DriveNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RequiredFileMissingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"완성 패키지 생성 중 오류가 발생했습니다: {exc}",
        ) from exc

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="Tulipa_Sunlover_complete.zip"',
        },
    )
