"""ERP가 만든 ZIP에서 신고 입력값과 첨부파일을 꺼낸다."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


class PayloadError(RuntimeError):
    pass


@dataclass
class ReportPayload:
    """신고 화면에 넣을 값과 첨부할 파일."""

    fields: dict[str, str]
    variety: str
    # 첨부파일: 화면의 첨부 항목 이름 → 실제 파일 경로
    attachments: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def missing_fields(self) -> list[str]:
        """값이 비어 있는 항목. 자동입력 전에 사람이 확인해야 한다."""
        return [name for name, value in self.fields.items() if not str(value).strip()]


# ZIP 안의 파일을 이름으로 알아본다.
# 앞자리 번호로 구분하려 했더니 인보이스가 '06_..._invoice_원본유지.pdf'로 나오고
# 처리요약도 '06_'으로 시작해서 겹쳤다. 번호는 상황에 따라 달라지므로 쓰지 않는다.
_ATTACHMENT_RULES = (
    ("품종사진_전체", ("전체사진",), ()),
    ("품종사진_근접", ("근접사진", "근접샷"), ()),
    ("신고서", ("신고서",), ("요약",)),
    ("검역합격증명서", ("phyto", "검역", "식검", "합격증"), ()),
    ("인보이스", ("invoice", "인보이스"), ("요약",)),
    ("종자업등록증", ("종자업",), ()),
    ("시료제출확약서", ("확약서",), ()),
)


def classify(file_name: str) -> str:
    """파일 이름을 보고 어느 첨부 항목인지 정한다."""
    name = file_name.lower()
    for label, words, blocked in _ATTACHMENT_RULES:
        if any(word.lower() in name for word in words) and not any(
            bad.lower() in name for bad in blocked
        ):
            return label
    return ""


def load_payload(zip_path: str | Path, extract_to: str | Path | None = None) -> ReportPayload:
    """ERP ZIP을 풀어서 신고 입력값과 첨부파일 경로를 돌려준다."""
    archive_path = Path(zip_path)
    if not archive_path.exists():
        raise PayloadError(f"ZIP을 찾을 수 없습니다: {archive_path}")

    target = Path(extract_to or archive_path.with_suffix(""))
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(target)
        names = archive.namelist()

    manifest_name = next((n for n in names if n.endswith("manifest.json")), None)
    if not manifest_name:
        raise PayloadError("ZIP에 manifest.json이 없습니다. ERP에서 만든 ZIP이 맞는지 확인하세요.")

    manifest = json.loads((target / manifest_name).read_text(encoding="utf-8"))
    fields = manifest.get("report_fields")
    if not fields:
        raise PayloadError(
            "manifest.json에 report_fields가 없습니다. "
            "구버전 ZIP이면 ERP에서 다시 생성해주세요."
        )

    attachments: dict[str, Path] = {}
    for name in names:
        label = classify(Path(name).name)
        if label and label not in attachments:
            attachments[label] = target / name

    return ReportPayload(
        fields=dict(fields),
        variety=str(manifest.get("variety") or ""),
        attachments=attachments,
        warnings=list(manifest.get("warnings") or []),
    )
