"""과거 신고 기록에서 작물 한글명과 품종 한글표기를 찾는다.

회사가 2023~2024년에 실제로 발급받은 신고 164건(`250110_생판신고 발급완료 리스트.xlsx`)에서
뽑았다. AI가 지어내는 이름이 아니라 **실제로 종자원에 통과된 표기**라, 신고서에 그대로 쓸 수 있다.

- 작물 한글명: 학명(속+종)으로 찾는다. AI가 'Hydrangea' 같은 영문을 돌려줘도 '수국'으로 채운다.
- 품종 한글표기: 학명+품종영문으로 찾는다. 규정상 사람이 정하는 이름이라 새로 만들지는 않고,
  전에 신고한 적 있는 품종일 때만 채운다.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "past_filings.json"


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, str], dict[str, str]]:
    try:
        data = json.loads(_DATA.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[past_filings] 과거 신고 자료를 읽지 못했습니다: {exc}", flush=True)
        return {}, {}
    return data.get("작물", {}), data.get("품종", {})


def binomial(scientific_name: str) -> str:
    """학명에서 속명+종소명만 남긴다. 명명자(L., W.Bartram)는 뺀다."""
    words = [w for w in re.split(r"\s+", str(scientific_name or "")) if w and w not in ("×", "x", "X")]
    keep: list[str] = []
    for word in words:
        if len(keep) == 2:
            break
        if keep and re.match(r"^[A-Z]", word):  # 명명자 시작
            break
        keep.append(word)
    return " ".join(keep).lower()


def crop_korean_name(scientific_name: str) -> str:
    """학명으로 작물 한글명을 찾는다. 없으면 빈 문자열."""
    crops, _ = _tables()
    key = binomial(scientific_name)
    if key in crops:
        return crops[key]

    # 종소명까지 일치하는 기록이 없으면 속 단위로 한 번 더 본다.
    genus = key.split(" ")[0]
    if genus:
        matches = {name for k, name in crops.items() if k.split(" ")[0] == genus}
        if len(matches) == 1:
            return matches.pop()
    return ""


def cultivar_korean_name(scientific_name: str, cultivar: str) -> str:
    """전에 신고한 적 있는 품종이면 그때 쓴 한글표기를 돌려준다."""
    _, cultivars = _tables()
    name = str(cultivar or "").strip().lower()
    if not name:
        return ""

    exact = cultivars.get(f"{binomial(scientific_name)}|{name}")
    if exact:
        return exact

    # 학명이 조금 달라도 품종명이 같으면 같은 품종으로 본다.
    matches = {v for k, v in cultivars.items() if k.split("|", 1)[1] == name}
    return matches.pop() if len(matches) == 1 else ""
