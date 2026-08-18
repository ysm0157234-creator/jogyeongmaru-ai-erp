"""HWP 5.x(.hwp) 문서 생성.

국립종자원에 제출하는 파일은 한글 `.hwp` 형식이어야 한다. `.hwp`는 OLE 복합문서
안에 자체 레코드 구조를 zlib으로 압축해 넣은 바이너리라서, 백지에서 새로 만들어 주는
파이썬 라이브러리가 없다. 대신 **실제 제출본을 템플릿으로 두고 내부를 고쳐 쓴다.**

동작 원리
---------
1. 본문(`BodyText/Section0`)을 zlib 해제하면 레코드가 연속으로 이어진 구조가 나온다.
   각 레코드 헤더 4바이트에 tagID(10비트) · level(10비트) · size(12비트)가 들어 있고,
   size가 0xFFF면 뒤에 4바이트 실제 크기가 따라온다.
2. `HWPTAG_PARA_TEXT`(67) 레코드의 본문이 UTF-16LE 문자열이다. 여기서 표식을 치환한다.
3. 글자 수가 바뀌면 **레코드 헤더의 size**와 **직전 `HWPTAG_PARA_HEADER`(66)의 글자 수**를
   같이 고쳐야 한다. 안 고치면 한글이 문서를 깨진 것으로 읽는다.
4. 사진은 `BinData/BIN000n` 스트림을 새 이미지로 교체한다.

크기 제약
---------
OLE 스트림은 **원래 크기를 넘겨서 쓸 수 없다**(넘기려면 컨테이너 전체를 재구성해야 한다).
그래서 새로 만든 데이터를 압축한 뒤 원래 크기에 못 미치는 만큼 0으로 채워 넣는다.
zlib은 압축 스트림 뒤의 잉여 바이트를 무시하므로 이 방식이 안전하다.
용량이 모자라면 사진을 점점 줄여가며 맞추고, 그래도 안 되면 명확한 오류를 낸다.
"""

from __future__ import annotations

import io
import re
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import olefile
from PIL import Image

# 본문 레코드 태그
_TAG_PARA_HEADER = 66
_TAG_PARA_TEXT = 67

# 품종 사진이 들어가는 BinData 슬롯 (템플릿 기준)
OVERALL_IMAGE_STREAM = "BinData/BIN0005.bmp"
CLOSEUP_IMAGE_STREAM = "BinData/BIN0006.bmp"

_SECTION_STREAM = "BodyText/Section0"


class HwpBinaryError(RuntimeError):
    pass


@dataclass
class HwpRecord:
    tag: int
    level: int
    payload: bytes
    extended: bool  # 크기를 4바이트로 따로 적는 형식인지


def _parse_records(data: bytes) -> list[HwpRecord]:
    records: list[HwpRecord] = []
    pos = 0

    while pos + 4 <= len(data):
        header = struct.unpack_from("<I", data, pos)[0]
        tag = header & 0x3FF
        level = (header >> 10) & 0x3FF
        size = (header >> 20) & 0xFFF
        pos += 4

        extended = size == 0xFFF
        if extended:
            size = struct.unpack_from("<I", data, pos)[0]
            pos += 4

        records.append(HwpRecord(tag, level, data[pos : pos + size], extended))
        pos += size

    return records


def _serialize_records(records: list[HwpRecord]) -> bytes:
    output = bytearray()

    for record in records:
        size = len(record.payload)
        # 원래 확장 형식이었거나, 12비트(0xFFF)에 담을 수 없을 만큼 커졌으면 확장 형식으로 쓴다.
        if record.extended or size >= 0xFFF:
            output += struct.pack(
                "<I", (record.tag & 0x3FF) | ((record.level & 0x3FF) << 10) | (0xFFF << 20)
            )
            output += struct.pack("<I", size)
        else:
            output += struct.pack(
                "<I", (record.tag & 0x3FF) | ((record.level & 0x3FF) << 10) | (size << 20)
            )
        output += record.payload

    return bytes(output)


def _apply_text(records: list[HwpRecord], replace) -> int:
    """PARA_TEXT 레코드에 replace(문자열)->문자열 을 적용하고 글자 수 정합성을 맞춘다."""
    changed = 0
    last_header: HwpRecord | None = None

    for record in records:
        if record.tag == _TAG_PARA_HEADER:
            last_header = record
            continue
        if record.tag != _TAG_PARA_TEXT:
            continue

        text = record.payload.decode("utf-16-le", errors="replace")
        updated = replace(text)
        if updated == text:
            continue

        new_payload = updated.encode("utf-16-le")
        # 글자 수 = UTF-16 코드 유닛 수. 문단 헤더의 글자 수도 같은 만큼 조정한다.
        delta = (len(new_payload) - len(record.payload)) // 2
        if delta and last_header is not None and len(last_header.payload) >= 4:
            count = struct.unpack_from("<I", last_header.payload, 0)[0]
            body = bytearray(last_header.payload)
            struct.pack_into("<I", body, 0, max(0, count + delta))
            last_header.payload = bytes(body)

        record.payload = new_payload
        changed += 1

    return changed


def _fit_stream(payload: bytes, capacity: int) -> bytes | None:
    """압축 후 원래 스트림 크기에 맞춰 0으로 채운다. 넘치면 None."""
    compressed = zlib.compress(payload, 9)[2:-4]  # raw deflate (zlib 헤더/체크섬 제외)
    if len(compressed) > capacity:
        return None
    return compressed + b"\x00" * (capacity - len(compressed))


def _encode_photo(image_bytes: bytes, capacity: int, target: tuple[int, int]) -> bytes:
    """사진을 템플릿 슬롯 용량 안에 들어가도록 BMP로 인코딩한다.

    사진 BMP는 거의 압축이 되지 않으므로, 용량을 넘기면 해상도를 낮춰가며 맞춘다.
    문서에 표시되는 크기는 별도로 기록되어 있어서 해상도만 낮아지고 배치는 그대로다.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise HwpBinaryError(f"사진을 열지 못했습니다: {exc}") from exc

    for scale in (1.0, 0.92, 0.85, 0.78, 0.70, 0.62, 0.55, 0.48, 0.40, 0.32, 0.25):
        size = (max(1, int(target[0] * scale)), max(1, int(target[1] * scale)))
        buffer = io.BytesIO()
        image.resize(size, Image.LANCZOS).save(buffer, format="BMP")
        fitted = _fit_stream(buffer.getvalue(), capacity)
        if fitted is not None:
            return fitted

    raise HwpBinaryError("사진을 템플릿 사진 슬롯 용량 안에 넣지 못했습니다.")


# 템플릿의 문단 슬롯. 별지 설명은 문단 개수가 고정이라 슬롯에 나눠 담고,
# 문장이 슬롯보다 많으면 마지막 슬롯에 이어 붙인다(문단을 새로 만들지 않는다).
CHARACTERISTIC_SLOTS = (
    "{{품종특성설명}}",
    "{{품종특성설명2}}",
    "{{품종특성설명3}}",
    "{{품종특성설명4}}",
)
BREEDING_SLOTS = ("{{육성과정설명}}",)


def _distribute(lines: list[str], slots: tuple[str, ...]) -> dict[str, str]:
    """문장 목록을 문단 슬롯에 배분한다. 슬롯보다 많으면 마지막 슬롯에 합친다."""
    filled: dict[str, str] = {slot: "" for slot in slots}
    if not lines:
        return filled

    head, tail = lines[: len(slots) - 1], lines[len(slots) - 1 :]
    for slot, line in zip(slots, head):
        filled[slot] = f" {line}"
    filled[slots[len(head)]] = " " + " ".join(tail)
    return filled


def _split_report_date(value: str) -> dict[str, str]:
    """'2025년 5월 13일' 같은 문자열에서 연·월·일 숫자만 뽑는다.

    템플릿은 서식의 자간을 살리려고 `{{년}}년     {{월}}월     {{일}}일` 처럼
    숫자 자리만 표식으로 두었다. 문서마다 자간이 달라서 통째로 치환할 수 없다.
    """
    numbers = re.findall(r"\d+", str(value or ""))
    if len(numbers) < 3:
        return {"{{년}}": "", "{{월}}": "", "{{일}}": ""}
    return {"{{년}}": numbers[0], "{{월}}": numbers[1], "{{일}}": numbers[2]}


def _build_replacements(data: "HwpReportData") -> dict[str, str]:
    from app.services.hwp_template_service import TEXT_FIELDS, _split_sentences

    values = {
        placeholder: str(getattr(data, field) or "")
        for placeholder, field in TEXT_FIELDS.items()
    }
    values.update(_split_report_date(data.report_date_spaced))
    values.update(_distribute(_split_sentences(data.characteristics), CHARACTERISTIC_SLOTS))
    values.update(_distribute(_split_sentences(data.breeding_process), BREEDING_SLOTS))
    return values


def _patch_section(section: bytes, values: dict[str, str]) -> bytes:
    records = _parse_records(zlib.decompress(section, -15))

    def replace(text: str) -> str:
        if "{{" not in text:
            return text
        for placeholder, value in values.items():
            if placeholder in text:
                text = text.replace(placeholder, value)
        return text

    _apply_text(records, replace)
    return _serialize_records(records)


def build_hwp_from_template(
    template_path: str | Path,
    data: "HwpReportData",
) -> bytes:
    """템플릿 .hwp의 표식을 채우고 사진을 교체해 완성된 .hwp 바이트를 돌려준다."""
    template = Path(template_path)
    if not template.exists():
        raise HwpBinaryError(f"HWP 템플릿이 없습니다: {template}")

    values = _build_replacements(data)

    with tempfile.NamedTemporaryFile(suffix=".hwp", delete=True) as handle:
        handle.write(template.read_bytes())
        handle.flush()

        source = olefile.OleFileIO(handle.name)
        try:
            if not source.exists(_SECTION_STREAM):
                raise HwpBinaryError(f"템플릿에 {_SECTION_STREAM}이 없습니다.")
            section = source.openstream(_SECTION_STREAM).read()
            capacities = {
                name: source.get_size(name.split("/"))
                for name in (OVERALL_IMAGE_STREAM, CLOSEUP_IMAGE_STREAM)
                if source.exists(name)
            }
        finally:
            source.close()

        patched = _patch_section(section, values)
        fitted = _fit_stream(patched, len(section))
        if fitted is None:
            raise HwpBinaryError(
                "본문이 템플릿 스트림 용량을 넘었습니다. "
                "품종 특성 설명 또는 육성과정 설명을 줄여주세요."
            )

        photos = {
            OVERALL_IMAGE_STREAM: (data.overall_image, (700, 700)),
            CLOSEUP_IMAGE_STREAM: (data.closeup_image, (695, 701)),
        }

        target = olefile.OleFileIO(handle.name, write_mode=True)
        try:
            target.write_stream(_SECTION_STREAM, fitted)
            for name, (image_bytes, size) in photos.items():
                capacity = capacities.get(name)
                if not capacity or not image_bytes:
                    continue
                target.write_stream(name, _encode_photo(image_bytes, capacity, size))
        finally:
            target.close()

        return Path(handle.name).read_bytes()
