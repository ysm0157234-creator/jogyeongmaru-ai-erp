from __future__ import annotations

import copy
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PIL import Image


class HwpTemplateError(RuntimeError):
    pass


@dataclass
class HwpReportData:
    representative: str
    birth_date: str
    address: str
    short_address: str
    company_name: str
    phone: str
    crop_common_name: str
    scientific_name: str
    variety_name: str
    origin_country: str
    seed_business_number: str
    quarantine_number: str
    characteristics: str
    breeding_process: str
    report_date_spaced: str
    overall_image: bytes
    closeup_image: bytes


TEXT_FIELDS = {
    "{{대표자}}": "representative",
    "{{생년월일}}": "birth_date",
    "{{주소}}": "address",
    "{{주소_축약}}": "short_address",
    "{{법인명칭}}": "company_name",
    "{{전화번호}}": "phone",
    "{{작물명}}": "crop_common_name",
    "{{학명}}": "scientific_name",
    "{{품종명}}": "variety_name",
    "{{원산지}}": "origin_country",
    "{{종자업등록번호}}": "seed_business_number",
    "{{검역합격번호}}": "quarantine_number",
    "{{작성일_공백}}": "report_date_spaced",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(
        (node.text or "")
        for node in paragraph.iter()
        if _local(node.tag) == "t"
    )


def _set_paragraph_text(paragraph: ET.Element, value: str) -> None:
    nodes = [node for node in paragraph.iter() if _local(node.tag) == "t"]
    if not nodes:
        raise HwpTemplateError("텍스트 노드가 없는 문단입니다.")
    nodes[0].text = value
    for node in nodes[1:]:
        node.text = ""


def _replace_text(root: ET.Element, placeholder: str, value: str) -> int:
    count = 0
    for paragraph in [e for e in root.iter() if _local(e.tag) == "p"]:
        text = _paragraph_text(paragraph)
        if placeholder in text:
            _set_paragraph_text(paragraph, text.replace(placeholder, value))
            count += 1
    return count


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return []
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?다])\s+", cleaned)
        if sentence.strip()
    ]


def _expand_paragraph_marker(
    root: ET.Element,
    marker: str,
    lines: list[str],
) -> None:
    for parent in root.iter():
        children = list(parent)
        for index, child in enumerate(children):
            if _local(child.tag) != "p":
                continue
            if marker not in _paragraph_text(child):
                continue
            if not lines:
                lines = [""]
            _set_paragraph_text(child, lines[0])
            insert_at = index + 1
            for line in lines[1:]:
                cloned = copy.deepcopy(child)
                _set_paragraph_text(cloned, line)
                parent.insert(insert_at, cloned)
                insert_at += 1
            return
    raise HwpTemplateError(f"템플릿에서 문단 표식을 찾지 못했습니다: {marker}")


def _to_bmp(image_bytes: bytes) -> bytes:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise HwpTemplateError(f"사진을 열지 못했습니다: {exc}") from exc
    output = io.BytesIO()
    image.save(output, format="BMP")
    return output.getvalue()


def build_hwpx_from_template(template_path: str | Path, data: HwpReportData) -> bytes:
    template = Path(template_path)
    if not template.exists():
        raise HwpTemplateError(f"HWPX 템플릿이 없습니다: {template}")

    try:
        with zipfile.ZipFile(template) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    except zipfile.BadZipFile as exc:
        raise HwpTemplateError("HWPX 템플릿이 손상되었습니다.") from exc

    section_name = "Contents/section0.xml"
    if section_name not in files:
        raise HwpTemplateError("Contents/section0.xml이 없습니다.")

    root = ET.fromstring(files[section_name])

    for placeholder, field in TEXT_FIELDS.items():
        _replace_text(root, placeholder, str(getattr(data, field) or ""))

    characteristic_lines = [f" {s}" for s in _split_sentences(data.characteristics)]
    breeding_lines = [f" {s}" for s in _split_sentences(data.breeding_process)]
    _expand_paragraph_marker(root, "{{품종특성설명}}", characteristic_lines)
    _expand_paragraph_marker(root, "{{육성과정설명}}", breeding_lines)

    files[section_name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    # 원본 양식의 사진 위치를 그대로 유지하며 바이너리만 교체
    if "BinData/image3.BMP" not in files or "BinData/image2.BMP" not in files:
        raise HwpTemplateError("원본 사진 슬롯(image3.BMP/image2.BMP)이 없습니다.")
    files["BinData/image3.BMP"] = _to_bmp(data.overall_image)
    files["BinData/image2.BMP"] = _to_bmp(data.closeup_image)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        if "mimetype" in files:
            archive.writestr("mimetype", files.pop("mimetype"), compress_type=zipfile.ZIP_STORED)
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def build_hwpx_report(
    *,
    template_path: str | Path,
    result_data: dict[str, Any],
    quarantine_number: str,
    report_date_spaced: str,
    overall_image: bytes,
    closeup_image: bytes,
    company: dict[str, str],
) -> bytes:
    return build_hwpx_from_template(
        template_path,
        HwpReportData(
            representative=company.get("representative", "황수영"),
            birth_date=company.get("birth_date", "1985. 5. 15."),
            address=company.get("address", "경기도 평택시 진위면 서촌로 38-9"),
            short_address=company.get("short_address", "경기 평택시 진위면 서촌로 38-9"),
            company_name=company.get("company_name", "농업회사법인 주식회사 조경마루"),
            phone=company.get("phone", "010-9377-3058"),
            crop_common_name=str(result_data.get("korean_name") or result_data.get("matched_name") or ""),
            scientific_name=str(result_data.get("scientific_name") or ""),
            variety_name=str(result_data.get("cultivar") or result_data.get("matched_name") or ""),
            origin_country=str(result_data.get("origin") or "네덜란드"),
            seed_business_number=company.get("seed_business_number", "제10-평택-2023-30-01호"),
            quarantine_number=quarantine_number,
            characteristics=str(result_data.get("characteristics_draft") or ""),
            breeding_process=str(result_data.get("breeding_process_draft") or ""),
            report_date_spaced=report_date_spaced,
            overall_image=overall_image,
            closeup_image=closeup_image,
        ),
    )
