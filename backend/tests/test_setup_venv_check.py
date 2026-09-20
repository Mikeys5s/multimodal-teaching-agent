"""`scripts/setup-venv.sh --check` 的自检测试（新增于 chore/venv-outside-project）。

## 为什么这个测试非写不可

`backend/.venv` 一旦被**建在项目内**（`python -m venv .venv`），本机的清理程序
就会成批删除它的文件（`.venv/Lib/site-packages/` 被清空过多次，`.git/refs` 也被删过）。
这正是 `scripts/setup-venv.sh` 存在的理由：venv 建在**项目外**，项目内只留一个 junction。

但"大家记得别手建"靠不住 —— 文档教的那条命令一照抄就中招。所以 `--check`
必须能**自己认出来**、把话说清楚，并且**只读**（出问题只告诉你怎么修）。
这个测试就是钉住它的判定与文案：用 `tmp_path` 造出三种真实情形，
跑**真实脚本进程**，验退出码与输出关键词。

| 造的情形 | 期望 |
|---|---|
| `backend/.venv` 不存在 | ❌ 未建，并给出 `bash scripts/setup-venv.sh`，退出码 1 |
| `backend/.venv` 是**真实目录** | ❌ 文案含「真实目录」「项目内」「会被删」，退出码 1 |
| `backend/.venv` 是 **junction** | ✅ 认出来是指向别处的链接 |

> ⚠️ 关于 junction 那条：它只断言"**放置**检查是 ✅"。测试里 junction 的**目标目录是空的**，
> 里面没有 `python.exe`，所以 `--check` 整体仍判"有问题"（退出码 1）。
> 这是**刻意**的：放置正确 ≠ 环境可用 —— venv 被删空时 `--check` 必须报警，
> 否则这个自检就没有意义了。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "setup-venv.sh"

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="本机没有 bash，跑不了 shell 脚本")


def _run_check(repo: Path, outside_venv: Path) -> subprocess.CompletedProcess[str]:
    """跑真实脚本进程做 `--check`（只读）。

    - `--repo <repo>`：把"仓库根"指到 tmp_path，于是它检查的是**我们造的** `backend/.venv`
    - `XIZHI_VENV_DIR`：把"项目外真实 venv"也指到 tmp_path，让 [4] 与机器状态无关
    """
    env = dict(os.environ)
    env["XIZHI_VENV_DIR"] = str(outside_venv)
    return subprocess.run(
        [BASH, str(SCRIPT), "--check", "--repo", str(repo)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )


def _make_junction(link: Path, target: Path) -> bool:
    """用 `cmd /c mklink /J` 造一个目录联接（不需要管理员权限）。成功返回 True。"""
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode == 0 and link.exists()


def test_check_reports_missing_venv(tmp_path: Path) -> None:
    """`backend/.venv` 不存在 → 报告「未建」并给出搭建命令，退出码 1。"""
    repo = tmp_path / "repo"
    (repo / "backend").mkdir(parents=True)

    r = _run_check(repo, tmp_path / "outside")

    assert r.returncode == 1, r.stdout + r.stderr
    assert "未建" in r.stdout, r.stdout
    assert "bash scripts/setup-venv.sh" in r.stdout, r.stdout


def test_check_flags_real_dir_venv_inside_project(tmp_path: Path) -> None:
    """`backend/.venv` 是真实目录（=`python -m venv .venv` 的后果）→ ❌ + 退出码 1。"""
    repo = tmp_path / "repo"
    (repo / "backend" / ".venv").mkdir(parents=True)  # 真实目录，不是 junction

    r = _run_check(repo, tmp_path / "outside")

    assert r.returncode == 1, r.stdout + r.stderr
    assert "❌" in r.stdout, r.stdout
    assert "真实目录" in r.stdout, r.stdout
    assert "项目内" in r.stdout, r.stdout
    assert "会被删" in r.stdout, r.stdout
    assert "bash scripts/setup-venv.sh --rebuild" in r.stdout, r.stdout


def test_check_accepts_junction(tmp_path: Path) -> None:
    """`backend/.venv` 是 junction → 放置检查 ✅，且指出它指向哪里。"""
    repo = tmp_path / "repo"
    target = tmp_path / "outside" / "xizhi-backend"
    link = repo / "backend" / ".venv"

    if not _make_junction(link, target):
        pytest.skip("本机无法创建 junction（mklink /J 失败）")

    r = _run_check(repo, target)

    assert "✅" in r.stdout, r.stdout
    assert "junction" in r.stdout, r.stdout
    assert "指向" in r.stdout, r.stdout
    # 不能把 junction 误判成项目内的真实目录
    assert "真实目录" not in r.stdout, r.stdout
    # 放置 ✅，但目标目录是空的（没有 python.exe）→ 整体仍判「有问题」
    assert r.returncode == 1, r.stdout + r.stderr
