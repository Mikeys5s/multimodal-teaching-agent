#!/usr/bin/env python
"""OCR 模型预取 + 离线自检（归属：P1 · D3 补充路径）。

## 这个脚本干什么

D3 的扫描件 OCR 走 `paddleocr`（PP-OCRv6 的 det + rec 两个模型，≈133 MB）。
模型默认落在用户目录下，**部署/CI 阶段先取好**，运行时就完全不需要联网。
本脚本做两件事：

1. **预取**：把两个模型放进 `<模型目录>`（默认 `~/.xizhi-ocr-models`），
   幂等 —— 已经完整就跳过，只打印体积；
2. **`--check` 离线自检**：在"只读已有缓存"的前提下跑一次最小 OCR
   （程序化生成的小图，不依赖任何素材文件），证明**不联网也能跑通**。

```bash
# 1) 预取模型（首次；已存在则秒退）
backend/.venv/Scripts/python.exe scripts/prefetch-ocr-models.py

# 2) 离线自检：断网也不能失败（脚本会主动掐断 socket，见下）
backend/.venv/Scripts/python.exe scripts/prefetch-ocr-models.py --check

# 换一个模型目录（比如 CI 的持久卷）
XIZHI_OCR_MODEL_DIR=D:/ci/ocr-models backend/.venv/Scripts/python.exe scripts/prefetch-ocr-models.py
```

## 为什么模型必须放在**项目外**

本机（以及同类 Windows 开发机）有一个清理程序会**按规则删项目目录里的文件**：
目录结构还在、文件没了（`.venv/Lib/site-packages` 下整包源码消失、`.git/refs` 整个
目录消失都实测发生过，见 `win-shell-git-pip-workarounds` 约束 0）。把 133 MB 模型
放进仓库目录，隔天就会变成"模型缺失"，而且报错长得像依赖装错了，极难定位。
所以：**模型目录固定在用户目录下**，`PADDLE_PDX_CACHE_HOME` 指过去，
仓库里只留这个脚本（几十 KB）。

## 幂等与取模型的顺序

1. 目标目录里两个模型都完整 → **直接跳过**（打印体积后退出，不加载任何模型）；
2. 否则先在 `~/.paddlex/official_models` 等已知缓存里找现成的副本 → **拷贝**过去
   （离线机器友好：不需要能连上模型仓，只要这台机器以前下过一次）；
3. 都找不到才让 paddlex 自己下载（需要网络，会打印中文进度）。

## `--check` 是真断网，不是"希望不联网"

`--check` 里会装一个 socket 守卫：任何 `connect()` 直接抛异常。同时设
`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1` 让 paddlex 别去做联网探测。
"没网也能跑"因此是被**证明**的，而不是被假设的 —— 只要有一次真的去连网，
自检就会失败并告诉你它想连哪里。
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.parse import ocr  # noqa: E402

#: 已知的历史缓存位置（第 2 步的拷贝来源）。paddlex 的默认缓存就在用户目录下。
_KNOWN_CACHES = (
    Path.home() / ".paddlex" / "official_models",
    # 注意：不要把仓库内的任何目录列进来 —— 那些路径明天可能就没了。
)


def _model_state(root: Path) -> tuple[list[str], int]:
    """返回 `(缺失的模型名, 已存在模型的合计字节数)`。

    "完整"的判据是 `inference.json` + `inference.pdiparams` 都在 —— 这是推理
    真正要读的两个文件；只看目录存在会把"下载到一半"当成"已就绪"。
    """
    missing: list[str] = []
    total = 0
    for name in ocr.MODEL_NAMES:
        path = root / "official_models" / name
        files = [path / "inference.json", path / "inference.pdiparams"]
        if not all(f.is_file() for f in files):
            missing.append(name)
            continue
        total += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return missing, total


def _copy_from_known_caches(root: Path, missing: list[str]) -> list[str]:
    """从已知缓存拷贝缺失的模型；返回仍缺失的模型名。"""
    for cache in _KNOWN_CACHES:
        still: list[str] = []
        for name in missing:
            src = cache / name
            dst = root / "official_models" / name
            if src.is_dir() and (src / "inference.pdiparams").is_file():
                print(f"  · 从 {cache} 拷贝 {name} …", flush=True)
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                still.append(name)
        missing = still
        if not missing:
            break
    return missing


def _download(root: Path, missing: list[str]) -> None:
    """让 paddlex 自己下载（唯一需要网络的路径）。"""
    print(f"  · 本地缓存里没有 {'、'.join(missing)}，开始下载（需要网络）…", flush=True)
    print(f"    下载目标：{root}（由 PADDLE_PDX_CACHE_HOME 指定）", flush=True)
    ocr.apply_model_cache_env()
    # 构造引擎 = 让 paddlex 去取模型；取完立刻释放，别占着内存。
    ocr.get_engine()
    ocr.release_engine()


def _check(root: Path) -> int:
    """离线自检：掐断 socket，跑一次最小 OCR，并核对识别文本。"""
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "1"
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(root)

    real_connect = socket.socket.connect

    def _blocked(self, address, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError(f"离线自检失败：脚本试图联网（connect {address!r}）")

    socket.socket.connect = _blocked  # type: ignore[method-assign]
    try:
        from PIL import Image, ImageDraw, ImageFont

        import numpy as np

        image = Image.new("RGB", (720, 200), "white")
        draw = ImageDraw.Draw(image)
        font = _pick_cjk_font(ImageFont)
        for i, text in enumerate(("网络层负责分组转发。", "传输层提供可靠交付。")):
            draw.text((20, 20 + i * 70), text, fill="black", font=font)
        expected = "网络层"

        print("  · 已掐断 socket（任何联网都会让自检失败）", flush=True)
        print("  · 加载引擎（只读本地缓存）…", flush=True)
        lines, dropped = ocr._lines_of_image(np.asarray(image))
        joined = "".join(line.text for line in lines)
        print(f"  · 识别到 {len(lines)} 行（丢弃低置信度 {dropped} 行）：{joined!r}", flush=True)
        if expected not in joined:
            print(f"  ✗ 自检未通过：识别结果里没有出现预期文本 {expected!r}", flush=True)
            return 1
        print("  ✓ 自检通过：断网状态下 OCR 可用（模型读的是本地缓存）", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 —— 自检要把失败原因说清楚，不往上抛
        print(f"  ✗ 自检失败：{type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        ocr.release_engine()


def _pick_cjk_font(image_font):  # noqa: ANN001, ANN202
    """挑一个本机有的中文字体；都没有就退回默认字体（自检会因识别不到而失败）。"""
    candidates = (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    for path in candidates:
        if Path(path).is_file():
            return image_font.truetype(path, 34)
    return image_font.load_default()


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR 模型预取与离线自检")
    parser.add_argument(
        "--check",
        action="store_true",
        help="离线自检：在断网前提下跑一次最小 OCR（模型必须已预取）",
    )
    args = parser.parse_args()

    root = ocr.model_dir()
    print(f"模型目录：{root}（项目外；XIZHI_OCR_MODEL_DIR 可覆盖）", flush=True)

    missing, total = _model_state(root)
    if missing:
        print(f"缺少模型：{'、'.join(missing)}", flush=True)
        missing = _copy_from_known_caches(root, missing)
        if missing:
            _download(root, missing)
        missing, total = _model_state(root)

    if missing:
        print(f"✗ 预取未完成，仍缺：{'、'.join(missing)}", flush=True)
        return 1

    print(f"✓ 模型就绪：{'、'.join(ocr.MODEL_NAMES)}", flush=True)
    print(f"  合计体积：{total / 1024 / 1024:.2f} MB（期望 ≈133 MB）", flush=True)

    if args.check:
        print("开始离线自检 …", flush=True)
        return _check(root)
    print("（加 --check 可做一次离线自检）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
