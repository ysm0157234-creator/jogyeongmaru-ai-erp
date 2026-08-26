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

_LOG: list[str] = []


def log(message: str) -> None:
    """터미널과 파일에 함께 남긴다.

    한 줄 쓸 때마다 파일에 반영한다. 중간에 죽어도 어디까지 갔는지 남아야
    진단이 된다(예전에는 끝까지 가야 저장돼서 정작 실패했을 때 파일이 없었다).
    """
    print(message, flush=True)
    _LOG.append(message)
    _write_log()


def _write_log() -> None:
    try:
        config.AUTOMATION_DIR.joinpath("last_run.log").write_text(
            "\n".join(_LOG), encoding="utf-8"
        )
    except Exception:
        pass


def _shot(page, name: str) -> None:
    """실패한 화면을 그림으로 남긴다."""
    try:
        path = config.AUTOMATION_DIR / f"last_run_{name}.png"
        page.screenshot(path=str(path), full_page=True)
        log(f"      화면 저장: {path.name}")
    except Exception:
        pass

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
    scope_page = page
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
                options = scope.eval_on_selector(
                    selector,
                    "el => [...el.options].map(o => o.text.trim())",
                )
                if value not in options:
                    close = [o for o in options if value in o or o in value]
                    todo.append(
                        f"{name}: 목록에 '{value}'가 없습니다"
                        + (f" (비슷한 항목: {', '.join(close[:3])})" if close else "")
                        + " — 직접 선택하세요"
                    )
                    continue
                scope.select_option(selector, label=value, timeout=5000)
            else:
                scope.fill(selector, value)
            done.append(f"{name} = {value[:44]}")
        except Exception as exc:
            todo.append(f"{name}: {type(exc).__name__} {exc}")

    list_done, list_todo = select_lists(scope_page, payload, field_map.get("list_selects", []))
    done.extend(list_done)
    todo.extend(list_todo)

    for name in field_map.get("manual", []):
        todo.append(f"{name}: 자동화 대상 아님 — 직접 처리")

    return done, todo


def select_lists(page: Page, payload: ReportPayload, items: list[dict]) -> tuple[list[str], list[str]]:
    """목록에서 고르기만 하면 되는 항목(종자업 등록번호 등)."""
    done: list[str] = []
    todo: list[str] = []
    for item in items:
        selector = item["selector"]
        wanted = str(payload.fields.get(item.get("field", ""), "")).strip()
        try:
            options = page.eval_on_selector(
                selector, "el => [...el.options].map(o => o.text.trim())"
            )
        except Exception:
            todo.append(f"{item['name']}: 목록을 찾지 못했습니다 — 직접 고르세요")
            continue

        # 등록번호는 '제10-평택-2023-30-01호'처럼 앞뒤 글자가 붙어 있어 부분 일치로 찾는다.
        core = wanted.strip("제호 ")
        match = next((o for o in options if core and core in o), None) or (
            options[0] if len(options) == 1 and options[0].strip() else None
        )

        # 목록이 비어 있으면 번호를 직접 넣고 [추가]를 눌러 목록에 올린다.
        if not match and item.get("input_selector") and core:
            try:
                page.fill(item["input_selector"], core, timeout=3000)
                page.click(item.get("add_button", "a:has-text('추가')"), timeout=4000)
                page.wait_for_timeout(1500)
                options = page.eval_on_selector(
                    selector, "el => [...el.options].map(o => o.text.trim())"
                )
                match = next((o for o in options if core in o), None)
                if match:
                    log(f"      {item['name']} 목록에 추가함")
            except Exception as exc:
                log(f"      {item['name']} 추가 실패: {type(exc).__name__}")

        if not match:
            todo.append(f"{item['name']}: 목록에서 '{wanted}'를 찾지 못했습니다 (있는 것: {options[:3]}) — 직접 고르세요")
            continue
        try:
            page.select_option(selector, label=match, timeout=4000)
            done.append(f"{item['name']} = {match}")
        except Exception as exc:
            todo.append(f"{item['name']}: {type(exc).__name__} — 직접 고르세요")

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
    # 검색은 한글 일반명이 없으면 속명으로 한다. 자동 선택 판정은 한글 일반명으로만 한다.
    keywords = [
        str(payload.fields.get(f, "")).strip()
        for f in entry.get("fields", [entry.get("field", "작물_검색어")])
    ]
    keywords = [k for i, k in enumerate(keywords) if k and k not in keywords[:i]]
    target = str(payload.fields.get(entry.get("match_field", "작물_일반명"), "")).strip()
    if not keywords:
        return None, "작물명·학명이 모두 비어 있음 — 팝업에서 직접 검색·선택하세요"
    keyword = keywords[0]

    # 팝업은 본문 '일반명' 칸의 값을 물고 열린다(팝업 URL에 crop_nm_kor로 실려 간다).
    # 그래서 팝업을 열기 전에 본문 칸부터 채운다.
    selector = entry.get("keyword_selector", "#crop_nm_kor")
    try:
        page.fill(selector, keyword)
        log(f"      본문 일반명 칸에 '{keyword}' 입력")
    except Exception as exc:
        # 검색으로만 채우게 막아둔 칸이면 fill이 통하지 않는다. 값을 직접 넣는다.
        try:
            page.evaluate(
                "([sel, val]) => { const el = document.querySelector(sel);"
                " el.removeAttribute('readonly'); el.value = val; }",
                [selector, keyword],
            )
            log(f"      본문 일반명 칸에 '{keyword}' 직접 대입 (fill 불가: {type(exc).__name__})")
        except Exception as exc2:
            log(f"      본문 일반명 칸 입력 실패: {type(exc2).__name__} {exc2}")

    openers = entry.get("openers") or [entry["opener"]]
    popup = None
    last_error = None
    for candidate in openers:
        try:
            count = page.locator(candidate).count()
        except Exception:
            count = -1
        log(f"      작물 [검색] 후보 '{candidate}' → {count}개")
        if count <= 0:
            continue
        try:
            popup = _open_popup(context, page, candidate)
            break
        except Exception as exc:
            last_error = exc
            log(f"        열기 실패: {type(exc).__name__}")

    try:
        if popup is None:
            raise last_error or RuntimeError("작물 [검색] 버튼을 찾지 못했습니다")
    except Exception as exc:
        _shot(page, "crop_opener")
        return None, f"작물 [검색] 버튼을 누르지 못했습니다: {type(exc).__name__} {str(exc)[:90]}"

    popup.wait_for_load_state("domcontentloaded")
    popup.wait_for_timeout(1200)
    log(f"      팝업 주소: {popup.url[:110]}")

    rows = _crop_rows(popup)
    log(f"      검색 결과 {len(rows)}건" + (f" → {[r['name'] for r in rows[:6]]}" if rows else ""))
    if not rows:
        # 팝업이 검색 없이 열렸으면 직접 검색한다.
        try:
            popup.fill("#crop_nm_kor", keyword)
            popup.click("a:has-text('검색')")
            popup.wait_for_load_state("domcontentloaded")
            popup.wait_for_timeout(2500)
            rows = _crop_rows(popup)
            log(f"      팝업 안에서 재검색 → {len(rows)}건")
        except Exception as exc:
            return None, f"작물 검색 실패: {type(exc).__name__} — 팝업에서 직접 검색·선택하세요"

    for alternate in keywords[1:]:
        if rows:
            break
        log(f"      '{keyword}' 결과 없음 → '{alternate}'로 다시 찾습니다")
        try:
            popup.fill("#crop_nm_kor", alternate)
            popup.click("a:has-text('검색')")
            popup.wait_for_load_state("domcontentloaded")
            popup.wait_for_timeout(2500)
            rows = _crop_rows(popup)
            keyword = alternate
            log(f"      검색 결과 {len(rows)}건" + (f" → {[r['name'].strip() for r in rows[:6]]}" if rows else ""))
        except Exception as exc:
            log(f"      재검색 실패: {type(exc).__name__}")

    if not rows:
        _shot(popup, "crop_popup")
        return None, f"'{keyword}' 검색 결과가 없음 — 팝업에서 직접 검색·선택하세요"

    names = ", ".join(r["name"].strip() for r in rows[:8])
    if not target:
        return None, (
            f"'{keyword}' 검색 결과 {len(rows)}건 (후보: {names}) — "
            "한글 일반명이 없어 자동으로 고르지 않았습니다. 열린 팝업에서 직접 [선택]하세요"
        )

    exact = [r for r in rows if r["name"].strip() == target]
    if len(exact) != 1:
        return None, (
            f"'{target}'와 정확히 일치하는 작물이 {len(exact)}개 (후보: {names}) "
            "— 열린 팝업에서 직접 [선택]하세요"
        )

    popup.click(f"a:has-text('선택') >> nth={exact[0]['index']}")
    settle(popup)          # 선택하면 팝업이 스스로 닫힌다
    settle(page, 800)      # 본문에 값이 반영될 시간
    return f"{exact[0]['name'].strip()} ({exact[0]['code']})", ""


def fill_char_sheet(context, page: Page, payload: ReportPayload, entry: dict, *, interactive: bool = True) -> tuple[list[str], list[str]]:
    """품종특성기술서 팝업을 채운다.

    작물별 특성표가 아니라 자유 서술 칸이라 ERP 조사 결과를 그대로 넣을 수 있다.
    다만 GMO 여부·작기·대조품종처럼 **신고인이 사실로 선언하는 항목**은 채우지 않는다.
    ERP에 근거 자료가 없고, 틀린 값이 신고서에 들어가면 안 되는 자리다.
    """
    done: list[str] = []
    todo: list[str] = []

    # 이 화면은 품종명이 정해져야 열린다. 비어 있으면 사이트가 안내창만 띄우고 끝난다.
    guard = entry.get("requires_field")
    watch = entry.get("requires_selector")
    filled = str(payload.fields.get(guard, "")).strip() if guard else ""
    if watch and not filled:
        try:
            filled = page.input_value(watch, timeout=2000).strip()
        except Exception:
            filled = ""
    if guard and not filled:
        return done, [f"특성기술서: {guard}이(가) 비어 있어 열지 못했습니다 — 품종명을 먼저 입력하세요"]

    try:
        popup = _open_popup(context, page, entry["opener"])
    except Exception as exc:
        _shot(page, "char_sheet")
        return done, [f"특성기술서 팝업이 열리지 않았습니다: {type(exc).__name__} — 직접 작성하세요"]
    try:
        for name, item in entry.get("fields", {}).items():
            selector = item["selector"]
            value = str(payload.fields.get(item["field"], "")).strip()
            source = "ZIP"
            if not value:
                value = str(item.get("default", "")).strip()
                source = "기본문구"
            if not value:
                log(f"      특성기술서 {name}: 넣을 값이 없음")
                todo.append(f"특성기술서 {name}: 값이 비어 있음")
                continue

            try:
                found = popup.locator(selector).count()
            except Exception:
                found = -1

            try:
                popup.fill(selector, value, timeout=4000)
                after = popup.input_value(selector, timeout=2000)
                log(f"      특성기술서 {name} ← {source} ({len(value)}자) / 칸 {found}개 / 실제 {len(after)}자")
                done.append(f"특성기술서 {name}")
            except Exception as exc:
                # 화면에 숨겨진 칸은 직접 값을 넣는다.
                try:
                    popup.evaluate(
                        "([sel, val]) => { const el = document.querySelector(sel);"
                        " el.removeAttribute('readonly'); el.disabled = false; el.value = val; }",
                        [selector, value],
                    )
                    log(f"      특성기술서 {name} ← {source} (직접 대입, fill 불가: {type(exc).__name__})")
                    done.append(f"특성기술서 {name} (숨김칸)")
                except Exception as exc2:
                    log(f"      특성기술서 {name} 실패: {type(exc2).__name__} / 칸 {found}개")
                    todo.append(f"특성기술서 {name}: {type(exc2).__name__}")

        # 신고인이 선언하는 항목. 요청에 따라 기본값을 넣되, 제출 전 확인이 필요하다.
        for choice in entry.get("choices", []):
            try:
                popup.check(choice["selector"], timeout=3000)
                done.append(f"특성기술서 {choice['name']}")
            except Exception:
                todo.append(f"특성기술서 {choice['name']}: 선택 실패 — 직접 고르세요")

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
                settle(popup)
                log("      특성기술서 입력완료 눌렀음")
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


def wait_for_crop(page: Page, seconds: int = 180) -> str:
    """사람이 팝업에서 작물을 고를 때까지 기다린다.

    작물이 정해지지 않으면 임시저장이 통과하지 못해 첨부까지 갈 수 없다.
    예전에는 여기서 실행을 끝냈는데, 사용자가 브라우저 앞에 있으므로
    고르는 것을 기다렸다가 나머지를 이어서 하는 편이 훨씬 낫다.
    """
    log(f"      작물 선택을 기다립니다 (최대 {seconds // 60}분). 팝업에서 [선택]을 누르세요.")
    for _ in range(seconds * 2):
        try:
            if page.is_closed():
                log("      창이 닫혀 작물 선택 대기를 멈춥니다.")
                return ""
            value = page.input_value("#crop_gubun", timeout=1000).strip()
            if value:
                picked = page.input_value("#crop_nm_kor", timeout=1000).strip()
                log(f"      작물 선택 확인: {picked} / {value}")
                return picked or value
        except Exception:
            pass
        page.wait_for_timeout(500)
    log("      작물 선택을 기다리다 시간이 지났습니다.")
    return ""


def verify_variety_name(context, page: Page, payload: ReportPayload, entry: dict) -> tuple[str | None, str]:
    """품종명 중복확인 팝업을 끝까지 처리한다.

    품종명칭을 넣고 [목록조회]를 누른 뒤, '사용가능한 품종명입니다'가 나오면 [선택]까지 누른다.
    이미 등록된 이름이면 고르지 않고 그대로 알린다. 이름을 다시 정하는 것은 신고인 몫이다.
    """
    name = str(payload.fields.get(entry.get("field", "품종_한글명"), "")).strip()
    if not name:
        # ZIP에 없으면 화면에 사람이 넣어둔 값을 쓴다.
        try:
            name = page.input_value(entry.get("source_selector", "#var_nm_kor"), timeout=2000).strip()
        except Exception:
            name = ""
    if not name:
        return None, "품종 한글명이 없어 중복확인을 하지 못했습니다"

    try:
        popup = _open_popup(context, page, entry["opener"])
    except Exception as exc:
        _shot(page, "varcheck_open")
        return None, f"중복확인 팝업이 열리지 않았습니다: {type(exc).__name__} — 직접 누르세요"

    try:
        popup.wait_for_load_state("domcontentloaded")
        settle(popup, 800)

        for selector in (
            "tr:has(th:has-text('품종명칭')) input[type=text]",
            "input[name=var_nm_kor]",
            "#var_nm_kor",
        ):
            try:
                popup.fill(selector, name, timeout=2500)
                log(f"      중복확인 품종명칭 = {name!r}")
                break
            except Exception:
                continue

        popup.click("a:has-text('목록조회'), button:has-text('목록조회'), input[value='목록조회']", timeout=6000)
        settle(popup, 2500)

        body = popup.inner_text("body", timeout=5000)
        if "사용가능" in body:
            popup.click("a:has-text('선택'), button:has-text('선택'), input[value='선택']", timeout=6000)
            settle(popup)
            settle(page, 800)
            log(f"      중복확인 통과 — {name!r} 선택")
            return name, ""

        _shot(popup, "varcheck_result")
        return None, f"중복확인: '{name}'이 사용가능으로 나오지 않았습니다 — 팝업에서 직접 확인하세요"
    except Exception as exc:
        _shot(popup, "varcheck")
        return None, f"중복확인 처리 실패: {type(exc).__name__} — 직접 하세요"
    finally:
        try:
            if not popup.is_closed():
                popup.close()
        except Exception:
            pass


def click_actions(page: Page, actions: list[dict], payload: ReportPayload) -> tuple[list[str], list[str]]:
    """입력 후 눌러야 하는 버튼(중복확인 등)을 순서대로 누른다."""
    done, failed = [], []
    for action in actions:
        name = action["name"]

        # 값이 있어야 의미가 있는 버튼은 값이 비면 누르지 않는다.
        # (중복확인은 품종명이 비어 있으면 확인할 대상 자체가 없다.)
        guard = action.get("requires_field")
        watch = action.get("requires_selector")
        filled = str(payload.fields.get(guard, "")).strip() if guard else ""
        if watch and not filled:
            try:
                filled = page.input_value(watch, timeout=2000).strip()
            except Exception:
                filled = ""
        if guard and not filled:
            log(f"      {name} 건너뜀 — {guard}이(가) 비어 있음")
            failed.append(f"{name}: {guard}이(가) 비어 있어 누르지 않았습니다")
            continue

        try:
            page.click(action["selector"], timeout=action.get("timeout", 8000))
            page.wait_for_timeout(action.get("wait", 1500))
            log(f"      {name} 눌렀음")
            done.append(name)
        except Exception as exc:
            log(f"      {name} 실패: {type(exc).__name__}")
            failed.append(f"{name}: {type(exc).__name__} — 직접 눌러야 함")
    return done, failed


_DIALOG_WATCHED: set[int] = set()


def watch_dialogs(page: Page) -> list[str]:
    """사이트가 띄우는 경고창 문구를 모아둔다.

    Playwright는 대화상자를 자동으로 닫아버린다. 그래서 '품종명을 입력하세요' 같은
    안내가 떠서 팝업이 안 열려도 겉으로는 그냥 시간만 지나간 것처럼 보였다.
    """
    messages: list[str] = []
    if id(page) in _DIALOG_WATCHED:
        return messages
    _DIALOG_WATCHED.add(id(page))

    def on_dialog(dialog):
        messages.append(dialog.message.strip())
        log(f"      [사이트 안내] {dialog.message.strip()}")
        try:
            dialog.accept()
        except Exception:
            pass

    page.on("dialog", on_dialog)
    return messages


def settle(target, ms: int = 1500) -> None:
    """잠깐 기다린다. 대상이 이미 닫혔으면 그냥 넘어간다.

    이 사이트의 팝업은 [선택]·[파일 첨부하기]를 누르면 스스로 닫힌다.
    닫힌 창을 기다리면 TargetClosedError가 나는데, 그걸 잡지 않아서
    작물 선택에 성공하고도 실행 전체가 죽었다.
    """
    try:
        if hasattr(target, "is_closed") and target.is_closed():
            return
        target.wait_for_timeout(ms)
    except Exception:
        return


def _open_popup(context, page: Page, opener: str, timeout: int = 15000):
    """본문의 버튼을 눌러 팝업 창을 연다."""
    before = set(context.pages)
    with context.expect_page(timeout=timeout) as info:
        page.click(opener)
    popup = info.value
    watch_dialogs(popup)
    popup.wait_for_load_state("domcontentloaded")
    if popup in before:
        raise RuntimeError("새 창이 열리지 않았습니다.")
    return popup


def _upload_in_popup(popup, path: Path, note: str) -> None:
    """팝업 안에서 파일을 고르고 올리기 버튼까지 누른다.

    첨부 팝업은 종류가 달라도 구조가 같다(파일칸 + 설명칸 + 올리기 버튼).
    설명칸은 비워도 되는 경우가 많아 note가 빈 문자열이면 건드리지 않는다.
    """
    popup.wait_for_selector("input[type=file]", timeout=10000)
    popup.set_input_files("input[type=file]", str(path))

    if note:
        for selector in ("#pic_rmrk", "input[name$=_rmrk]", "input[name*=rmrk]"):
            try:
                popup.fill(selector, note, timeout=2000)
                break
            except Exception:
                continue

    # 버튼 이름이 화면마다 조금씩 다르다.
    for label in ("파일 첨부하기", "파일 올리기", "첨부하기", "올리기", "등록"):
        try:
            popup.click(f"a:has-text('{label}'), button:has-text('{label}'), input[value='{label}']", timeout=3000)
            settle(popup)
            return
        except Exception:
            continue

    raise RuntimeError("파일 올리기 버튼을 찾지 못했습니다")


def _main_page(context, fallback):
    """본문(신고서 작성) 페이지를 다시 잡는다.

    임시저장을 하면 화면이 새로 뜨고 팝업이 남아 있을 수도 있다.
    저장 전에 들고 있던 페이지 객체를 그대로 쓰면 엉뚱한 창을 건드리게 된다.
    """
    for page in context.pages:
        try:
            if not page.is_closed() and "cvwAppMstReg" in page.url:
                return page
        except Exception:
            continue
    return fallback


def attach(context, payload: ReportPayload, field_map: dict, fallback=None) -> tuple[list[str], list[str]]:
    """임시저장 이후 열리는 [파일첨부] 팝업에 파일을 올린다."""
    attached: list[str] = []
    remaining: list[str] = []

    page = _main_page(context, fallback or context.pages[0])
    log(f"   - 첨부 대상 화면: {page.url[:90]}")

    for label, entry in field_map.get("attachments", {}).items():
        source = entry.get("source", label)
        path = payload.attachments.get(source)
        if not path or not Path(path).exists():
            remaining.append(f"{label}: ZIP에 {source} 파일이 없음")
            continue

        opener = entry["opener"]
        try:
            count = page.locator(opener).count()
        except Exception:
            count = -1
        log(f"      {label} 여는 버튼 '{opener}' → {count}개")
        if count <= 0:
            remaining.append(f"{label}: [파일첨부] 버튼을 찾지 못했습니다 — 직접 올려야 함")
            continue

        popup = None
        try:
            popup = _open_popup(context, page, opener, timeout=20000)
            _upload_in_popup(popup, Path(path), entry.get("note", ""))
            attached.append(f"{label} = {Path(path).name}")
            log(f"      {label} 첨부 완료")
        except Exception as exc:
            _shot(page, f"attach_{label}")
            remaining.append(f"{label}: {type(exc).__name__} — 직접 올려야 함")
            log(f"      {label} 첨부 실패: {type(exc).__name__} {str(exc)[:90]}")
        finally:
            try:
                if popup and not popup.is_closed():
                    popup.close()
            except Exception:
                pass
            # 첨부가 하나 끝나면 본문을 새로 읽어야 다음 팝업이 갱신된 상태로 열린다.
            # 이걸 안 하면 두 번째 사진이 올라간 것처럼 보이고 실제로는 등록되지 않는다.
            try:
                page.reload(wait_until="domcontentloaded")
                settle(page, 1200)
            except Exception:
                settle(page, 800)

    for name in field_map.get("manual_attachments", []):
        remaining.append(f"{name}: 직접 처리")

    return attached, remaining


def run(zip_path: str | Path, *, interactive: bool = True) -> dict:
    """ZIP 하나로 신고 화면을 채운다. 결과를 요약해서 돌려준다."""
    payload = load_payload(zip_path)
    field_map = load_field_map()

    done: list[str] = []
    todo: list[str] = [f"입력값 없음: {name}" for name in payload.missing_fields()]

    log(f"=== 신고 자동입력 시작: {payload.variety} ===")
    playwright, browser, context, page = open_session()
    watch_dialogs(page)

    # 브라우저를 재사용하므로 이전 실행의 작성 화면이 열려 있을 수 있다.
    # 목록으로 돌아가서 새 신고서를 연다.
    for extra in list(context.pages)[1:]:
        try:
            extra.close()
        except Exception:
            pass
    page.goto(config.REPORT_LIST_URL, wait_until="domcontentloaded")
    settle(page, 1000)

    try:
        page.click("a:has-text('신고서작성하기')", timeout=10000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2000)
    except Exception as exc:
        log(f"   ! 신고서작성하기 진입 실패: {type(exc).__name__}")
        _shot(page, "enter_form")
        todo.append(f"신고서작성하기 진입 실패: {type(exc).__name__} — 직접 이동하세요")
        if interactive:
            input("\n  신고 작성 화면으로 직접 이동한 뒤 Enter > ")

    # 작물 선택이 학명·작물분류를 덮어쓰므로 입력보다 먼저 한다.
    crop_ok = True
    crop = field_map.get("crop_search")
    if crop:
        try:
            picked, problem = select_crop(context, page, payload, crop)
        except Exception as exc:
            _shot(page, "crop")
            picked, problem = None, f"작물 검색 중 오류: {type(exc).__name__} {str(exc)[:80]}"
        if picked:
            done.append(f"작물 선택 = {picked}")
        else:
            todo.append(f"작물 검색: {problem}")
            if interactive:
                input("\n  작물을 팝업에서 직접 선택한 뒤 Enter > ")
                crop_ok = True
            else:
                picked = wait_for_crop(page)
                if picked:
                    done.append(f"작물 선택(직접) = {picked}")
                else:
                    crop_ok = False

    log("   - 입력값 채우는 중")
    filled, filled_todo = fill(page, payload, field_map)
    log(f"     입력 {len(filled)}건 / 직접처리 {len(filled_todo)}건")
    for line in filled_todo:
        log(f"       · {line}")
    done.extend(filled)
    todo.extend(filled_todo)

    # 사이트가 품종명 확정(중복확인)을 먼저 요구하므로 특성기술서보다 앞에 둔다.
    check = field_map.get("variety_check")
    if check:
        picked, problem = verify_variety_name(context, page, payload, check)
        if picked:
            done.append(f"품종명 중복확인 = {picked}")
        else:
            todo.append(problem)

        # 중복확인에서 품종을 고르면 사이트가 관련 칸을 다시 그리면서 영문명 등을
        # 지워버린다. 확인이 끝난 뒤 그 칸들을 다시 채운다.
        refill = {
            name: entry
            for name, entry in field_map.get("fields", {}).items()
            if name in field_map.get("refill_after_check", [])
        }
        if refill:
            again, again_todo = fill(page, payload, {"fields": refill})
            done.extend(f"{line} (중복확인 후 재입력)" for line in again)
            todo.extend(again_todo)

    pressed, unpressed = click_actions(page, field_map.get("actions_after_fill", []), payload)
    done.extend(pressed)
    todo.extend(unpressed)

    sheet = field_map.get("char_sheet")
    if sheet:
        sheet_done, sheet_todo = fill_char_sheet(
            context, page, payload, sheet, interactive=interactive
        )
        done.extend(sheet_done)
        todo.extend(sheet_todo)

    if not crop_ok:
        todo.append("작물이 끝내 선택되지 않아 임시저장·첨부를 진행하지 못했습니다")
        todo.append("[종자원 접수요청] — 내용을 확인하고 직접 누르세요")
        close_session(playwright, browser, context, keep_open=True)
        _write_log()
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
            log("   - 임시저장 완료")
        except Exception as exc:
            todo.append(f"임시저장 실패: {type(exc).__name__} — 직접 누르세요")
            if interactive:
                input("\n  임시저장을 직접 누른 뒤 Enter > ")
                saved = True

    if saved:
        # 종자업 등록번호 목록은 저장 뒤에 채워지는 경우가 있어 여기서 다시 시도한다.
        retry = [i for i in field_map.get("list_selects", []) if any(
            i["name"] in line for line in todo
        )]
        if retry:
            page = _main_page(context, page)
            again_done, again_todo = select_lists(page, payload, retry)
            done.extend(again_done)
            todo = [line for line in todo if not any(i["name"] in line for i in retry)]
            todo.extend(again_todo)

        log("   - 첨부 시작")
        attached, remaining = attach(context, payload, field_map, page)
        log(f"     첨부 {len(attached)}건 / 직접처리 {len(remaining)}건")
        done.extend(attached)
        todo.extend(remaining)
    else:
        todo.append("첨부 건너뜀 — 임시저장이 되지 않았습니다")

    todo.append("[종자원 접수요청] — 내용을 확인하고 직접 누르세요")

    # 사람이 확인하고 제출해야 하므로 브라우저는 닫지 않는다.
    close_session(playwright, browser, context, keep_open=True)
    _write_log()
    return {"variety": payload.variety, "done": done, "todo": todo}
