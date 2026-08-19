"""신고 화면 자동 입력의 실제 동작.

어떤 경우에도 **[종자원 접수요청]은 누르지 않는다.** 입력·첨부까지만 하고
브라우저를 열어둔 채 끝낸다. 사람이 확인하고 제출한다.

interactive=False 이면 사람에게 묻지 않고, 사람 판단이 필요한 항목은
결과의 todo 목록에 남긴다(웹앱 버튼으로 실행할 때 쓴다).
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


_CROP_ROWS = """
() => [...document.querySelectorAll('a')]
  .filter(a => a.innerText.trim() === '선택')
  .map((a, index) => {
    const row = a.closest('tr');
    const name = row && row.querySelector('input[name=crop_nm_kor]');
    const code = row && row.querySelector('input[name=crop_cd]');
    return { index, name: name ? name.value : '', code: code ? code.value : '' };
  })
"""


def _crop_rows(popup) -> list[dict]:
    """검색 결과 행을 읽는다. 검색 직후에는 화면이 바뀌는 중일 수 있어 두 번 시도한다."""
    for _ in range(2):
        try:
            return popup.evaluate(_CROP_ROWS)
        except Exception:
            popup.wait_for_timeout(1500)
    return []


def select_crop(context, page: Page, payload: ReportPayload, entry: dict) -> tuple[str | None, str]:
    """작물 검색 팝업에서 작물을 고른다.

    검색어와 **정확히 같은** 작물이 하나일 때만 자동으로 선택한다.
    작물 분류는 신고 내용의 근간이라, 비슷한 이름 중에서 임의로 고르면 안 된다.
    (예: '유카'로 검색하면 대왕유카·다화유카리·무지개유카리 등이 함께 나온다.)
    """
    keyword = str(payload.fields.get(entry.get("field", "작물_일반명"), "")).strip()
    if not keyword:
        return None, "작물명이 비어 있음 — 직접 검색해야 함"

    # 팝업은 본문 '일반명' 칸의 값을 물고 열린다(팝업 URL에 crop_nm_kor로 실려 간다).
    # 그래서 팝업을 열기 전에 본문 칸부터 채운다.
    try:
        page.fill(entry.get("keyword_selector", "#crop_nm_kor"), keyword)
    except Exception:
        pass

    popup = _open_popup(context, page, entry["opener"])
    popup.wait_for_load_state("domcontentloaded")
    popup.wait_for_timeout(1200)

    rows = _crop_rows(popup)
    if not rows:
        # 팝업이 검색 없이 열렸으면 직접 검색한다.
        try:
            popup.fill("#crop_nm_kor", keyword)
            popup.click("a:has-text('검색')")
            popup.wait_for_load_state("domcontentloaded")
            popup.wait_for_timeout(2500)
            rows = _crop_rows(popup)
        except Exception as exc:
            return None, f"작물 검색 실패: {type(exc).__name__} — 팝업에서 직접 검색·선택하세요"

    if not rows:
        return None, f"'{keyword}' 검색 결과가 없음 — 팝업에서 직접 검색·선택하세요"

    exact = [r for r in rows if r["name"].strip() == keyword]
    if len(exact) != 1:
        names = ", ".join(r["name"] for r in rows[:8])
        return None, (
            f"'{keyword}'와 정확히 일치하는 작물이 {len(exact)}개 (후보: {names}) "
            "— 열린 팝업에서 직접 [선택]하세요"
        )

    popup.click(f"a:has-text('선택') >> nth={exact[0]['index']}")
    popup.wait_for_timeout(1500)
    return f"{exact[0]['name']} ({exact[0]['code']})", ""


def fill_char_sheet(context, page: Page, payload: ReportPayload, entry: dict, *, interactive: bool = True) -> tuple[list[str], list[str]]:
    """품종특성기술서 팝업을 채운다.

    작물별 특성표가 아니라 자유 서술 칸이라 ERP 조사 결과를 그대로 넣을 수 있다.
    다만 GMO 여부·작기·대조품종처럼 **신고인이 사실로 선언하는 항목**은 채우지 않는다.
    ERP에 근거 자료가 없고, 틀린 값이 신고서에 들어가면 안 되는 자리다.
    """
    done: list[str] = []
    todo: list[str] = []

    popup = _open_popup(context, page, entry["opener"])
    try:
        for name, item in entry.get("fields", {}).items():
            value = str(payload.fields.get(item["field"], "")).strip()
            if not value:
                todo.append(f"특성기술서 {name}: 값이 비어 있음")
                continue
            try:
                popup.fill(item["selector"], value)
                done.append(f"특성기술서 {name}")
            except Exception:
                # 화면에 숨겨진 칸은 직접 값을 넣는다.
                try:
                    popup.evaluate(
                        "([sel, val]) => { const el = document.querySelector(sel); el.value = val; }",
                        [item["selector"], value],
                    )
                    done.append(f"특성기술서 {name} (숨김칸)")
                except Exception as exc:
                    todo.append(f"특성기술서 {name}: {type(exc).__name__}")

        for name in entry.get("manual", []):
            todo.append(f"특성기술서 {name}: 신고인이 판단할 항목 — 직접 선택")

        if entry.get("submit"):
            if interactive:
                print("\n  품종특성기술서 내용을 확인하고 [입력완료]를 누르세요.")
                print("  (자동으로 누르려면 a, 직접 처리하려면 Enter)")
                choice = input("  > ").strip().lower()
            else:
                choice = "a"
            if choice == "a":
                popup.click(entry["submit"])
                popup.wait_for_timeout(1500)
                done.append("특성기술서 입력완료")
            else:
                input("  팝업 처리를 마친 뒤 Enter > ")

    finally:
        if not popup.is_closed():
            try:
                popup.close()
            except Exception:
                pass

    return done, todo


def click_actions(page: Page, actions: list[dict]) -> tuple[list[str], list[str]]:
    """입력 후 눌러야 하는 버튼(중복확인 등)을 순서대로 누른다."""
    done, failed = [], []
    for action in actions:
        try:
            page.click(action["selector"], timeout=action.get("timeout", 8000))
            page.wait_for_timeout(action.get("wait", 1500))
            done.append(action["name"])
        except Exception as exc:
            failed.append(f"{action['name']}: {type(exc).__name__} — 직접 눌러야 함")
    return done, failed


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



def run(zip_path: str | Path, *, interactive: bool = True) -> dict:
    """ZIP 하나로 신고 화면을 채운다. 결과를 요약해서 돌려준다."""
    payload = load_payload(zip_path)
    field_map = load_field_map()

    done: list[str] = []
    todo: list[str] = [f"입력값 없음: {name}" for name in payload.missing_fields()]

    playwright, browser, context, page = open_session()
    page.goto(config.REPORT_LIST_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)

    try:
        page.click("a:has-text('신고서작성하기')", timeout=10000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)
    except Exception as exc:
        todo.append(f"신고서작성하기 진입 실패: {type(exc).__name__} — 직접 이동하세요")
        if interactive:
            input("\n  신고 작성 화면으로 직접 이동한 뒤 Enter > ")

    # 작물 선택이 학명·작물분류를 덮어쓰므로 입력보다 먼저 한다.
    crop_ok = True
    crop = field_map.get("crop_search")
    if crop:
        picked, problem = select_crop(context, page, payload, crop)
        if picked:
            done.append(f"작물 선택 = {picked}")
        else:
            todo.append(f"작물 검색: {problem}")
            if interactive:
                input("\n  작물을 팝업에서 직접 선택한 뒤 Enter > ")
            else:
                crop_ok = False

    filled, filled_todo = fill(page, payload, field_map)
    done.extend(filled)
    todo.extend(filled_todo)

    sheet = field_map.get("char_sheet")
    if sheet:
        sheet_done, sheet_todo = fill_char_sheet(
            context, page, payload, sheet, interactive=interactive
        )
        done.extend(sheet_done)
        todo.extend(sheet_todo)

    pressed, unpressed = click_actions(page, field_map.get("actions_after_fill", []))
    done.extend(pressed)
    todo.extend(unpressed)

    # 작물이 정해지지 않으면 임시저장이 통과하지 못하고 첨부도 열리지 않는다.
    # 반쯤 실패한 상태로 밀어붙이지 말고 여기서 멈춘다.
    if not crop_ok:
        todo.append(
            "작물을 열린 팝업에서 직접 선택한 뒤, [임시저장]과 첨부를 이어서 진행하세요 "
            "(자동 진행은 여기서 멈춥니다)"
        )
        todo.append("[종자원 접수요청] — 내용을 확인하고 직접 누르세요")
        close_session(playwright, browser, context, keep_open=True)
        return {"variety": payload.variety, "done": done, "todo": todo}

    # 첨부는 임시저장 후에만 열린다.
    save = field_map.get("save_draft")
    saved = False
    if save:
        try:
            page.click(save["selector"], timeout=10000)
            page.wait_for_timeout(save.get("wait", 4000))
            for label in ("확인", "예"):
                try:
                    page.click(f"a:has-text('{label}'), button:has-text('{label}')", timeout=1500)
                    page.wait_for_timeout(1500)
                    break
                except Exception:
                    continue
            saved = True
            done.append("임시저장")
        except Exception as exc:
            todo.append(f"임시저장 실패: {type(exc).__name__} — 직접 누르세요")
            if interactive:
                input("\n  임시저장을 직접 누른 뒤 Enter > ")
                saved = True

    if saved:
        attached, remaining = attach(context, payload, field_map)
        done.extend(attached)
        todo.extend(remaining)
    else:
        todo.append("첨부 건너뜀 — 임시저장이 되지 않았습니다")

    todo.append("[종자원 접수요청] — 내용을 확인하고 직접 누르세요")

    # 사람이 확인하고 제출해야 하므로 브라우저는 닫지 않는다.
    close_session(playwright, browser, context, keep_open=True)
    return {"variety": payload.variety, "done": done, "todo": todo}
