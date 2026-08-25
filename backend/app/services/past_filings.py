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


# 회사가 실제로 써 온 표기 방식을 보여주는 예시.
# 두 갈래가 뚜렷하다.
#   1) 발음되는 이름은 소리대로 적는다        (Midwinter Fire -> 미드윈터 파이어)
#   2) 자음만 늘어선 코드는 알파벳 이름을 적는다 (HAOPR012 -> 에이치에이오피알012)
_STYLE_EXAMPLES = (
    ("Hurricane", "허리케인"),
    ("Midwinter Fire", "미드윈터 파이어"),
    ("Anny's Winter Orange", "애니스 윈터 오렌지"),
    ("Baby Blue", "베이비 블루"),
    ("The President", "더 프레지던트"),
    ("Ville de Lyon", "빌리 디 리옹"),
    ("Mirror Jam", "미러잼"),
    ("Wims Red", "윔스레드"),
    ("Royal Purple", "로열퍼플"),
    ("Summer Chocolate", "썸머초콜릿"),
    ("Strawberry Fields", "스트로베리필드"),
    ("Heckenpracht", "헤켄프라치"),
    ("Danica", "데니카"),
    ("Snowbelle", "스노우벨"),
    ("Rensun", "렌썬"),
    ("Evipo106", "에비포106"),
    ("Verpaalen02", "페르파렌2"),
    ("Biv01", "비브01"),
    ("Darkap1", "다크아프1"),
    ("Minall2", "민올2"),
    ("Rwoods6", "알우즈6"),
    ("JWN Wood4", "제이더블유엔우드4"),
    ("HAOPR012", "에이치에이오피알012"),
    ("NCHA2", "엔시에이치에이2"),
    ("JS4", "제이에스4"),
    ("ZR1", "제트알1"),
    ("TVP1", "티브이피1"),
    ("GRHP11", "지알에이치피11"),
    ("MUNN001", "엠유엔엔001"),
    ("NC2016-2", "엔씨2016-2"),
)


def suggest_cultivar_korean(scientific_name: str, cultivar: str) -> str:
    """품종 한글표기를 정한다.

    전에 신고한 품종이면 그때 표기를 그대로 쓴다. 생산·수입판매 신고는 늘 새 품종이라
    대부분은 기록에 없으므로, 회사가 써 온 표기 방식을 예시로 주고 AI에게 음차를 시킨다.
    결과는 초안 화면에 보이므로 사람이 확인하고 고칠 수 있다.
    """
    known = cultivar_korean_name(scientific_name, cultivar)
    if known:
        return known

    name = str(cultivar or "").strip()
    if not name:
        return ""

    try:
        from app.services.gemini_service import GeminiService

        result = GeminiService().structure_json(transliteration_prompt(name))
        korean = str((result.data or {}).get("korean") or "").strip()
    except Exception as exc:
        print(f"[past_filings] 품종 한글표기 생성 실패 {name!r}: {type(exc).__name__} {exc}", flush=True)
        return ""

    # 한글이 하나도 없으면 음차가 아니라 뭔가 잘못 온 것이다.
    return korean if re.search(r"[가-힣]", korean) else ""


def suggest_crop_korean(scientific_name: str) -> str:
    """작물 한글명을 정한다.

    과거 신고 기록에 있으면 그 표기를 그대로 쓴다. 없으면(처음 다루는 속·종)
    AI에게 국명을 묻는다. 종자원 작물 등록부는 한글로 찾기 때문에 영문 이름으로는
    검색이 되지 않는다.
    """
    known = crop_korean_name(scientific_name)
    if known:
        return known

    name = str(scientific_name or "").strip()
    if not name:
        return ""

    try:
        from app.services.gemini_service import GeminiService

        result = GeminiService().structure_json(crop_name_prompt(name))
        korean = str((result.data or {}).get("korean") or "").strip()
    except Exception as exc:
        print(f"[past_filings] 작물 한글명 조회 실패 {name!r}: {type(exc).__name__} {exc}", flush=True)
        return ""

    return korean if re.search(r"[가-힣]", korean) else ""


def crop_name_prompt(scientific_name: str) -> str:
    """작물 국명을 묻는 프롬프트. 회사가 써 온 표기를 예시로 보여준다."""
    crops, _ = _tables()
    samples = "\n".join(f"{k} -> {v}" for k, v in list(crops.items())[:20])
    return (
        "너는 국립종자원 품종 생산·수입판매 신고서를 작성한다.\n"
        "학명에 해당하는 식물의 한글 이름(국명)을 답하라.\n\n"
        "우리 회사가 신고서에 써 온 표기다. 같은 방식으로 답하라.\n"
        f"{samples}\n\n"
        "규칙\n"
        "1. 국가표준식물목록에 쓰이는 국명을 쓴다.\n"
        "2. 품종명은 빼고 작물 이름만 쓴다.\n"
        "3. 학명을 소리대로 옮기지 말고 실제 국명을 쓴다"
        " (Yucca filamentosa는 '유카'가 아니라 '실유카').\n"
        "4. 국명이 확실하지 않으면 빈 문자열로 답한다.\n\n"
        f"학명: {scientific_name}\n\n"
        '결과를 {"korean": "국명"} 형태의 JSON으로만 답하라.'
    )


def transliteration_prompt(cultivar: str) -> str:
    """품종명 한글표기를 물어보는 프롬프트. 회사 표기 방식을 예시로 보여준다."""
    samples = "\n".join(f"{eng} -> {kor}" for eng, kor in _STYLE_EXAMPLES)
    return (
        "너는 국립종자원 품종 생산·수입판매 신고서를 작성한다.\n"
        "품종명(영문)을 한글 표기로 바꿔라. 뜻을 번역하지 말고 소리대로 적는다.\n\n"
        "우리 회사가 지금까지 신고한 표기 방식이다. 이 방식을 그대로 따라라.\n"
        f"{samples}\n\n"
        "규칙\n"
        "1. 발음되는 이름은 소리대로 적는다.\n"
        "2. 자음만 늘어서서 발음할 수 없는 약자는 알파벳 이름을 하나씩 적는다"
        " (J=제이, W=더블유, H=에이치, Z=제트, R=알, C=씨 또는 시).\n"
        "3. 숫자는 그대로 둔다. 앞의 0도 원문 그대로 둔다.\n"
        "4. 아포스트로피(')는 뺀다.\n"
        "5. 뜻을 옮기지 않는다. Red를 '빨강'으로 적지 않는다.\n\n"
        f"품종명: {cultivar}\n\n"
        '결과를 {"korean": "한글표기"} 형태의 JSON으로만 답하라.'
    )
