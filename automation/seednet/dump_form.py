"""1단계: 신고 작성 화면의 입력 항목 구조를 파일로 뽑아낸다.

신고 폼은 로그인 안쪽이라 미리 볼 수 없다. 추측으로 선택자를 짜면 틀리므로,
먼저 실제 화면 구조를 뽑아서 그것을 보고 입력 매핑(field_map.json)을 만든다.

    python -m seednet.dump_form
"""

from __future__ import annotations

import json

from seednet import config
from seednet.browser import close_session, open_session


_EXTRACT = """
() => {
  const label = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    const cell = el.closest('td');
    if (cell) {
      const row = cell.closest('tr');
      const th = row && row.querySelector('th');
      if (th) return th.innerText.trim();
    }
    return '';
  };
  const nodes = [...document.querySelectorAll('input,select,textarea,button,a.btn')];
  return {
    url: location.href,
    title: document.title,
    headings: [...document.querySelectorAll('h1,h2,h3,legend,caption')]
      .map(h => h.innerText.trim()).filter(Boolean).slice(0, 40),
    controls: nodes.map(el => ({
      tag: el.tagName.toLowerCase(),
      type: el.type || '',
      name: el.name || '',
      id: el.id || '',
      label: label(el),
      text: (el.innerText || el.value || '').trim().slice(0, 40),
      options: el.tagName === 'SELECT'
        ? [...el.options].map(o => ({ value: o.value, text: o.text.trim() })).slice(0, 30)
        : undefined,
      required: el.required || false,
      hidden: el.type === 'hidden' || !el.offsetParent,
    })),
  };
}
"""


def _snapshot(context) -> dict:
    """열려 있는 모든 창(팝업 포함)과 프레임을 함께 담는다.

    파일첨부·작물검색 같은 기능이 새 창으로 뜨는 경우가 많아서,
    현재 페이지만 보면 정작 필요한 구조를 놓친다.
    """
    pages = []
    for index, page in enumerate(context.pages):
        try:
            dump = page.evaluate(_EXTRACT)
        except Exception as exc:
            pages.append({"error": str(exc), "url": page.url})
            continue
        dump["window"] = index
        dump["frames"] = []
        for frame in page.frames[1:]:
            try:
                dump["frames"].append(frame.evaluate(_EXTRACT))
            except Exception as exc:
                dump["frames"].append({"error": str(exc), "url": frame.url})
        pages.append(dump)
    return {"windows": pages}


def _summarize(dump: dict) -> None:
    for window in dump["windows"]:
        if "error" in window:
            print(f"  [창] 읽기 실패 {window['url']}: {window['error']}")
            continue
        visible = [c for c in window["controls"] if not c["hidden"]]
        files = [c for c in window["controls"] if c["type"] == "file"]
        print(f"\n  [창 {window['window']}] {window['url']}")
        print(f"    제목 {window['headings'][:5]}")
        print(f"    입력 {len(window['controls'])}개(보임 {len(visible)}) 프레임 {len(window['frames'])} 파일칸 {len(files)}")
        for control in files:
            print(f"      >> 파일칸  name={control['name']} id={control['id']} {control['label'][:24]}")
        for control in visible[:18]:
            mark = control["label"] or control["text"]
            print(f"      {control['tag']:<7} {control['type']:<9} name={control['name']:<18} {mark[:24]}")


def main() -> None:
    playwright, browser, context, page = open_session()
    snapshots: list[dict] = []
    try:
        page.goto(config.REPORT_LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        print("=" * 66)
        print("  신고 화면은 여러 단계로 나뉘어 있을 수 있습니다.")
        print("  목록에서 '신고서작성하기'를 누르고, 화면이 바뀔 때마다 캡처하세요.")
        print()
        print("    Enter  현재 화면을 캡처")
        print("    q      캡처를 마치고 저장")
        print("=" * 66)

        while True:
            answer = input(f"\n[{len(snapshots)}개 캡처됨] Enter=캡처 / q=종료 > ").strip().lower()
            if answer == "q":
                break
            dump = _snapshot(context)
            snapshots.append(dump)
            print(f"\n--- {len(snapshots)}번째 캡처 ---")
            _summarize(dump)

        if not snapshots:
            print("캡처한 화면이 없습니다.")
            return

        config.FORM_DUMP.parent.mkdir(parents=True, exist_ok=True)
        config.FORM_DUMP.write_text(
            json.dumps({"snapshots": snapshots}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n저장: {config.FORM_DUMP}  (화면 {len(snapshots)}개)")
    finally:
        close_session(playwright, browser, context, keep_open=True)
        print("브라우저는 열어둡니다. 확인 후 직접 닫으세요.")


if __name__ == "__main__":
    main()
