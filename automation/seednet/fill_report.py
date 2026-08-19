"""2단계: 신고 화면을 자동으로 채우고 **제출 직전에 멈춘다.**

    python -m seednet.fill_report "<ERP가 만든 ZIP 경로>"

이 스크립트는 신고(제출) 버튼을 절대 누르지 않는다. 값 입력과 파일 첨부까지만 하고
브라우저를 열어둔 채로 끝난다. 내용을 확인한 뒤 사람이 직접 신고 버튼을 누른다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import Page

from seednet import config
from seednet.browser import close_session, open_session
from seednet.payload import ReportPayload, load_payload

FIELD_MAP = config.FIELD_MAP


class FieldMapError(RuntimeError):
    pass


def load_field_map() -> dict:
    """dump_form.py 결과를 보고 사람이 작성한 입력 매핑."""
    if not FIELD_MAP.exists():
        raise FieldMapError(
            f"{FIELD_MAP}가 없습니다.\n"
            "  먼저 `python -m seednet.dump_form`으로 화면 구조를 뽑고,\n"
            "  automation/field_map.example.json을 참고해 매핑을 작성하세요."
        )
    return json.loads(FIELD_MAP.read_text(encoding="utf-8"))


def _target(page: Page, mapping: dict):
    """매핑이 프레임을 지정했으면 그 프레임에서 찾는다."""
    frame_url = mapping.get("frame")
    if not frame_url:
        return page
    for frame in page.frames:
        if frame_url in frame.url:
            return frame
    raise FieldMapError(f"프레임을 찾지 못했습니다: {frame_url}")


def _resolve(entry: dict, payload: ReportPayload) -> str:
    """넣을 값을 정한다. value가 있으면 고정값, 없으면 ZIP에서 가져온다."""
    if "value" in entry:
        return str(entry["value"])
    return str(payload.fields.get(entry["field"], ""))


def fill(page: Page, payload: ReportPayload, field_map: dict) -> tuple[list[str], list[str]]:
    done: list[str] = []
    todo: list[str] = []

    for name, entry in field_map.get("fields", {}).items():
        kind = entry.get("kind", "text")
        selector = entry["selector"]
        scope = _target(page, entry)

        # 라디오·체크박스는 값이 필요 없다. 지정한 선택지를 고르기만 한다.
        if kind in ("radio", "check"):
            try:
                scope.check(selector)
                done.append(f"{name} → {entry.get('note', selector)}")
            except Exception as exc:
                todo.append(f"{name}: {type(exc).__name__} {exc}")
            continue

        value = _resolve(entry, payload)
        if not value.strip():
            todo.append(f"{name}: 값이 비어 있음 — 직접 입력 필요")
            continue

        try:
            if kind == "select":
                scope.select_option(selector, label=value)
            else:
                scope.fill(selector, value)
            done.append(f"{name} = {value[:44]}")
        except Exception as exc:
            todo.append(f"{name}: {type(exc).__name__} {exc}")

    for label, entry in field_map.get("attachments", {}).items():
        path = payload.attachments.get(entry.get("source", label))
        if not path or not Path(path).exists():
            todo.append(f"{label}: ZIP에 파일이 없음")
            continue
        try:
            scope = _target(page, entry)
            scope.set_input_files(entry["selector"], str(path))
            done.append(f"{label} 첨부 = {Path(path).name}")
        except Exception as exc:
            todo.append(f"{label}: 자동 첨부 실패 — 직접 첨부 필요 ({type(exc).__name__})")

    for name in field_map.get("manual", []):
        todo.append(f"{name}: 자동화 대상 아님 — 직접 처리")

    return done, todo


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    payload = load_payload(sys.argv[1])
    field_map = load_field_map()

    missing = payload.missing_fields()
    if missing:
        print("주의: 값이 비어 있는 항목이 있습니다 →", ", ".join(missing))
    for warning in payload.warnings:
        print("ERP 경고:", warning)

    playwright, browser, context, page = open_session()
    try:
        page.goto(config.REPORT_LIST_URL, wait_until="domcontentloaded")
        print("\n신고 '작성/신규신청' 화면까지 이동한 뒤 Enter를 누르세요.")
        input("준비되면 Enter > ")

        done, failed = fill(page, payload, field_map)

        print("\n" + "=" * 62)
        print(f"  자동 입력 완료: {len(done)}개")
        for line in done:
            print("   +", line)
        if failed:
            print(f"\n  직접 입력해야 하는 항목: {len(failed)}개")
            for line in failed:
                print("   !", line)
        print("=" * 62)
        print("\n  신고(제출) 버튼은 누르지 않았습니다.")
        print("  화면 내용을 확인한 뒤 직접 신고 버튼을 눌러 주세요.")
        input("\n확인이 끝나면 Enter를 눌러 이 스크립트를 종료합니다 > ")
    finally:
        # 사람이 제출해야 하므로 브라우저는 절대 닫지 않는다.
        close_session(playwright, browser, context, keep_open=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
