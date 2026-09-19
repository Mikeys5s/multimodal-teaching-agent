#!/usr/bin/env python
"""文件消失哨兵（归属：全队共用）。

## 为什么需要它

本仓库所在机器上反复出现「**工作区文件被成批删掉**」的现象，已发生多次：
`.venv/Lib/site-packages/` 被清空、`.git/objects/pack/` 消失、`backend/` 下的
源码被批量删除（`git restore .` 能恢复，因为文件还在 git 里）。

**根因未定责。** 目前有两条线索指向「高频改写工作区的 git 操作」：
`git rebase`（P1 复现两次）、`git checkout` / `merge`（P2 观察到时间吻合）。
但 `.venv` 被清空与 git 无关，所以**不能过早收口**。

这个脚本的作用是**抓到现行**：在文件消失的**当下**拿到精确时间点和消失清单，
再对照当时在跑什么操作 —— 比事后猜有用得多。

## 三种用法

```bash
# ① 对照实验（推荐）：快照 → 做一次 git 操作 → 比对
python scripts/watch-files.py --snapshot /tmp/before.json
git switch some-branch          # 或 rebase / merge / pull
python scripts/watch-files.py --compare /tmp/before.json

# ② 持续盯梢：发现文件数下降就告警
python scripts/watch-files.py --watch --interval 30

# ③ 只看当前状态
python scripts/watch-files.py --summary
```

## 抓到之后请记录

把「**消失清单 + 当时正在跑的命令 + 时间**」发到相关 Issue —— 三条信息缺一不可。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 只盯这些后缀：既覆盖被删过的类型，又不至于把仓库扫成几万行
WATCH_SUFFIXES = {".py", ".sh", ".md", ".toml", ".json", ".pack", ".idx", ".db", ".ts", ".tsx"}

# 这些目录不扫：体积大、易变、且与"源码被删"无关
SKIP_DIRS = {
    ".learnbuddy",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "build",
    ".git/objects",  # git 对象单独按 pack/idx 精确看
}


def iter_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix not in WATCH_SUFFIXES:
            continue
        yield rel


def scan(root: Path) -> dict[str, dict[str, object]]:
    """返回 {相对路径: {size, mtime}}。"""
    out: dict[str, dict[str, object]] = {}
    for rel in iter_files(root):
        try:
            st = (root / rel).stat()
        except OSError:
            continue
        out[rel.as_posix()] = {"size": st.st_size, "mtime": int(st.st_mtime)}
    return out


def summarize(root: Path, snap: dict[str, dict[str, object]]) -> None:
    by_ext: dict[str, int] = {}
    by_top: dict[str, int] = {}
    for rel in snap:
        p = Path(rel)
        by_ext[p.suffix] = by_ext.get(p.suffix, 0) + 1
        top = p.parts[0] if len(p.parts) > 1 else "(根目录)"
        by_top[top] = by_top.get(top, 0) + 1

    print(f"扫描根：{root}")
    print(f"文件总数：{len(snap)}\n")
    print("按后缀：")
    for ext, n in sorted(by_ext.items(), key=lambda kv: -kv[1]):
        print(f"  {ext:<8} {n}")
    print("\n按顶层目录：")
    for top, n in sorted(by_top.items(), key=lambda kv: -kv[1]):
        print(f"  {top:<20} {n}")


def cmd_snapshot(root: Path, out: Path) -> int:
    snap = scan(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    print(f"已写入快照：{out}（{len(snap)} 个文件）")
    print("现在去做你要验证的那一步操作，然后跑 --compare。")
    return 0


def cmd_compare(root: Path, before_file: Path) -> int:
    before: dict[str, dict[str, object]] = json.loads(before_file.read_text(encoding="utf-8"))
    after = scan(root)

    gone = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    changed = sorted(
        rel
        for rel in set(before) & set(after)
        if before[rel].get("mtime") != after[rel].get("mtime")
    )

    print(f"快照：{before_file}")
    print(f"对比：前 {len(before)} 个文件 → 后 {len(after)} 个文件\n")

    if gone:
        print(f"🔴 消失了 {len(gone)} 个文件：")
        # 按顶层目录归类，便于看模式
        buckets: dict[str, list[str]] = {}
        for rel in gone:
            key = "/".join(Path(rel).parts[:3])
            buckets.setdefault(key, []).append(rel)
        for key in sorted(buckets):
            print(f"  [{key}]  {len(buckets[key])} 个")
            for rel in buckets[key][:4]:
                print(f"      - {rel}")
            if len(buckets[key]) > 4:
                print(f"      … 还有 {len(buckets[key]) - 4} 个")
        print()
        print("  ⚠️ 请**立刻记录**：当时正在跑什么命令、几点几分。")
        print("     然后回报到 Issue —— 这三条信息缺一不可。")
    else:
        print("✅ 没有文件消失")

    if added:
        print(f"\n新增 {len(added)} 个文件")
    if changed:
        print(f"内容有变 {len(changed)} 个文件")

    return 1 if gone else 0


def cmd_watch(root: Path, interval: int) -> int:
    prev = scan(root)
    print(f"开始盯梢（{interval}s 一轮）。Ctrl+C 停止。基线 {len(prev)} 个文件\n")
    round_no = 0
    while True:
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n已停止")
            return 0
        round_no += 1
        cur = scan(root)
        gone = sorted(set(prev) - set(cur))
        if gone:
            stamp = time.strftime("%H:%M:%S")
            print(f"🔴 [{stamp}] 第 {round_no} 轮：消失 {len(gone)} 个文件")
            for rel in gone[:10]:
                print(f"      - {rel}")
            if len(gone) > 10:
                print(f"      … 还有 {len(gone) - 10} 个")
            print("  ⚠️ 记下这个时间点，立刻查当时在跑什么\n")
        else:
            print(f"  [{time.strftime('%H:%M:%S')}] 正常（{len(cur)} 个文件）")
        prev = cur


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="文件消失哨兵 —— 抓「工作区文件被成批删除」的现行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--root", default=str(REPO_ROOT), help="扫描根目录（默认仓库根）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", metavar="FILE", help="把当前状态写成快照")
    g.add_argument("--compare", metavar="FILE", help="与快照比对，有文件消失则返回 1")
    g.add_argument("--watch", action="store_true", help="持续盯梢")
    g.add_argument("--summary", action="store_true", help="只打印当前状态概览")
    ap.add_argument("--interval", type=int, default=30, help="--watch 的轮询间隔（秒）")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"根目录不存在：{root}", file=sys.stderr)
        return 2

    if args.snapshot:
        return cmd_snapshot(root, Path(args.snapshot))
    if args.compare:
        return cmd_compare(root, Path(args.compare))
    if args.watch:
        return cmd_watch(root, args.interval)
    summarize(root, scan(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
