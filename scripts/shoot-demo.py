"""一键拍「平台截图」——**给 PPT 用**。

    python scripts/shoot-demo.py                  # 拍全部
    python scripts/shoot-demo.py --only graph     # 只拍一张
    python scripts/shoot-demo.py --out D:/tmp/shots

## 为什么要有它

**2026-10-08 拍这批截图时踩了两个坑**（已进 `web-screenshots-reliable` skill）：
  ① 静态 `chrome --screenshot` **截不到 SPA 的内容**（图谱空白 / 空态）
  ② Playwright 自带的浏览器版本不匹配，**要显式指系统已有的 chrome**

**⇒ 10/11 做 PPT 终版时要重拍一遍。这个脚本把那两个坑绕过去了。**

## 它拍什么（**和 PPT 的对应关系**）

| 文件 | 页面 | 对应 PPT |
|---|---|---|
| `graph.png` | `/graph` | 成果 ① 知识图谱 |
| `path.png` | `/path`（**点了知识点**） | 成果 ② 学习路径 |
| `tutor.png` | `/tutor`（**问了 1 次**） | 成果 ③ 多轮答疑 |
| `overview.png` | `/` | 备用（首页入口） |
| `report.png` | `/report` | 备用（校验体系） |

**⚠️ 每条都带「必须等什么」** —— 这是今天两次失败换来的。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

CHROME = (r"C:/Users/admin/AppData/Local/ms-playwright/chromium-1223"
          r"/chrome-win64/chrome.exe")
BASE_DEFAULT = "http://120.77.177.171:8000"


def main() -> int:
    ap = argparse.ArgumentParser(description="一键拍平台截图（给 PPT 用）")
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--out", default=r"D:\muti_tagent\docs\ppt\shots")
    ap.add_argument("--only", default="", help="只拍某一张：graph/path/tutor/overview/report")
    a = ap.parse_args()

    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if not pathlib.Path(CHROME).exists():
        print(f"  ❌ 找不到 chrome：{CHROME}")
        print("     ⇒ 换一台机器时先改这个常量（或 `find $LOCALAPPDATA/ms-playwright -name chrome.exe`）")
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ 没装 playwright：pip install playwright")
        return 1

    want = {a.only} if a.only else {"graph", "path", "tutor", "overview", "report"}

    with sync_playwright() as pw:
        # ⚠️ **必须显式给 executable_path** —— 否则 Playwright 会去找它自带的那个版本
        #    （今天报过：要 `chromium_headless_shell-1243`，而系统只有 `1223`）。
        browser = pw.chromium.launch(executable_path=CHROME,
                                     args=["--no-sandbox", "--disable-gpu"])
        page = browser.new_page(viewport={"width": 1440, "height": 900},
                                device_scale_factor=2)
        page.set_default_timeout(60000)

        def shot(name: str, url: str, wait_ms: int, note: str) -> None:
            f = out / f"{name}.png"
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(wait_ms)
            page.screenshot(path=str(f))
            kb = f.stat().st_size / 1024
            # ⭐ **大小是廉价的前置信号**：空壳约 90 KB，有内容 300 KB+
            flag = "✅" if kb > 150 else "⚠️ 可能截到空壳"
            print(f"      {flag} {f.name}  {kb:.0f} KB   （{note}）")

        if "graph" in want:
            print("  [graph] 等 Cytoscape 画完 —— **不等就是空白**")
            shot("graph", f"{a.base}/graph", 7000, "成果① 知识图谱")

        if "path" in want:
            print("  [path] 必须点一个知识点 —— **不点就是空态**")
            page.goto(f"{a.base}/path", wait_until="networkidle")
            page.wait_for_timeout(2500)
            clicked = False
            for kw in ("5.3 TCP 拥塞控制", "第 5 章", "CONGESTION CONTROL",
                       "END-TO-END", "INTERNETWORKING"):
                try:
                    loc = page.get_by_text(kw, exact=False).first
                    if loc.count() and loc.is_visible():
                        loc.click()
                        clicked = True
                        print(f"         点了「{kw}」")
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not clicked:
                print("         ⚠️ 没点到 —— 选择器要更新（先 dump 页面上可点元素的文本）")
            page.wait_for_timeout(3500)
            f = out / "path.png"
            page.screenshot(path=str(f))
            print(f"      {'✅' if f.stat().st_size > 150_000 else '⚠️'} "
                  f"{f.name}  {f.stat().st_size / 1024:.0f} KB   （成果② 学习路径）")

        if "tutor" in want:
            print("  [tutor] 填问题 **并点「提问」** —— 只填不点，回复区还是空的")
            page.goto(f"{a.base}/tutor", wait_until="networkidle")
            page.wait_for_timeout(2500)
            # ① 优先点页面自带的示例问题（**dump 出来的**）—— 它只**填入输入框**，不提交
            filled = False
            for kw in ("慢启动为什么叫慢启动？", "三次握手为什么不是两次？",
                       "子网掩码是怎么用的？"):
                try:
                    loc = page.get_by_text(kw, exact=True).first
                    if loc.count() and loc.is_visible():
                        loc.click()
                        filled = True
                        print(f"         已填入示例问题「{kw}」")
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not filled:
                for ph in ("输入", "问题", "ask"):
                    try:
                        box = page.get_by_placeholder(ph, exact=False).first
                        if box.count() and box.is_visible():
                            box.fill("慢启动为什么叫慢启动？")
                            filled = True
                            print("         已手动填入问题")
                            break
                    except Exception:  # noqa: BLE001
                        continue

            # ② ⚠️ **关键一步：真的点「提问」** ——
            #    **踩过的坑**：只点示例问题按钮**只会填进输入框**，不提交；
            #    而截出来的图回复区仍是"提问后你会依次看到三件事"，
            #    **看着像有内容（324 KB），实际是空态**。
            clicked_send = False
            for label in ("提问", "发送", "提交", "Ask"):
                try:
                    btn = page.get_by_role("button", name=label).first
                    if btn.count() and btn.is_visible():
                        btn.click()
                        clicked_send = True
                        print(f"         ✅ 点了「{label}」按钮")
                        break
                except Exception:  # noqa: BLE001
                    continue
            if not clicked_send:
                try:
                    page.get_by_text("提问", exact=True).last.click()
                    clicked_send = True
                    print("         ✅ 点了「提问」（按文本兜底）")
                except Exception:  # noqa: BLE001
                    print("         ⚠️ 没找到「提问」按钮 —— 选择器要更新")
                if not clicked_send:
                    print("         ⚠️ 没问上 —— 选择器要更新")
            page.wait_for_timeout(10000)      # 等 SSE 流完
            f = out / "tutor.png"
            page.screenshot(path=str(f))
            print(f"      {'✅' if f.stat().st_size > 150_000 else '⚠️'} "
                  f"{f.name}  {f.stat().st_size / 1024:.0f} KB   （成果③ 多轮答疑）")

        for name, path, note in (("overview", "/", "备用：首页"),
                                 ("report", "/report", "备用：校验体系")):
            if name in want:
                shot(name, f"{a.base}{path}", 3000, note)

        browser.close()

    print()
    print("  ⇒ 拍完了。**下一步用 `python .learnbuddy/_gh/geometry_check.py` 验排版**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
