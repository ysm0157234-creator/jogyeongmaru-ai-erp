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


def _open_popup(context, page: Page, opener: str, timeout: int = 15000):
    """본문의 [파일첨부] 링크를 눌러 팝업 창을 연다."""
    before = set(context.pages)
    with context.expect_page(timeout=timeout) as info:
        page.click(opener)
    popup = info.value
    popup.wait_for_load_state("domcontentloaded")
    if popup in before:
        raise RuntimeError("새 창이 열리지 않았습니다.")
    return popup


def _upload_in_popup(popup, path: Path, note: str) -> None:
    """팝업 안에서 파일을 고르고 첨부 버튼을 누른다.

    첨부 팝업은 종류가 달라도 구조가 같다(파일칸 + 설명칸 + '파일 첨부하기').
    그래서 선택자를 종류별로 적지 않고 공통 규칙으로 찾는다.
    """
    popup.wait_for_selector("input[type=file]", timeout=10000)
    popup.set_input_files("input[type=file]", str(path))

    if note:
        for selector in ("#pic_rmrk", "input[name$=_rmrk]"):
            try:
                popup.fill(selector, note)
                break
            except Exception:
                continue

    popup.click("a:has-text('파일 첨부하기')")
    popup.wait_for_timeout(1500)


def attach(context, payload: ReportPayload, field_map: dict) -> tuple[list[str], list[str]]:
    """임시저장 이후 열리는 [파일첨부] 팝업에 파일을 올린다."""
    attached: list[str] = []
    remaining: list[str] = []

    page = context.pages[0]
    mapping = field_map.get("attachments", {})

    for label, entry in mapping.items():
        source = entry.get("source", label)
        path = payload.attachments.get(source)
        if not path or not Path(path).exists():
            remaining.append(f"{label}: ZIP에 {source} 파일이 없음")
            continue

        popup = None
        try:
            popup = _open_popup(context, page, entry["opener"])
            _upload_in_popup(popup, Path(path), entry.get("note", ""))
            attached.append(f"{label} = {Path(path).name}")
        except Exception as exc:
            remaining.append(f"{label}: {type(exc).__name__} {str(exc)[:70]} — 직접 올려야 함")
        finally:
            if popup and not popup.is_closed():
                try:
                    popup.close()
                except Exception:
                    pass

    for name in field_map.get("manual_attachments", []):
        remaining.append(f"{name}: 직접 처리")

    return attached, remaining


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

        done, todo = fill(page, payload, field_map)

        print("\n" + "=" * 66)
        print(f"  1단계 입력 완료: {len(done)}개")
        for line in done:
            print("   +", line)
        if todo:
            print(f"\n  직접 처리할 항목: {len(todo)}개")
            for line in todo:
                print("   !", line)
        print("=" * 66)

        # 이 사이트는 임시저장을 해야 첨부 기능이 열린다.
        # 저장 버튼은 사람이 누른다. 자동화는 저장 이후 첨부만 돕는다.
        print("\n  첨부는 [임시저장] 이후에만 가능합니다.")
        print("  화면에서 직접 [임시저장]을 누르고, 첨부 화면이 열리면 Enter를 누르세요.")
        print("  (첨부를 건너뛰려면 s 를 입력하세요)")
        answer = input("\n  임시저장 완료 후 Enter / s=건너뛰기 > ").strip().lower()

        if answer != "s":
            attached, remaining = attach(context, payload, field_map)
            print("\n" + "=" * 66)
            print(f"  2단계 첨부 완료: {len(attached)}개")
            for line in attached:
                print("   +", line)
            if remaining:
                print(f"\n  직접 첨부할 항목: {len(remaining)}개")
                for line in remaining:
                    print("   !", line)
            print("=" * 66)

        print("\n  [종자원 접수요청] 버튼은 누르지 않았습니다.")
        print("  화면 내용을 확인한 뒤 직접 눌러 신고를 마치세요.")
        input("\n확인이 끝나면 Enter를 눌러 이 스크립트를 종료합니다 > ")

    finally:
        # 사람이 제출해야 하므로 브라우저는 절대 닫지 않는다.
        close_session(playwright, browser, context, keep_open=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
