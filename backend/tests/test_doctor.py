"""`scripts/doctor.py` 的测试（归属：P1 / Issue #20）。

## 为什么这个测试非写不可

doctor.py 的卖点是"**默认什么都不会改**"，而这恰恰是最容易被后来者顺手破坏的
性质（比如给 `--fix-refs` 加一句"顺手把坏的删掉"）。所以下面每个用例都是
**行为断言**，不是"跑一次没报错"：

| 造什么现场 | 断言 |
|---|---|
| 健康仓库 | `--check` 退出码 0，且各检查项都出现在输出里 |
| 把 `.git/refs` 改名移走 | `--check` 退出码 1，且明确说 "refs 缺失" |
| 把已跟踪文件改名移走 | `--check` 报出它；`--restore`（dry-run）**不动**文件；`--yes` 才恢复 |
| 造一个坏引用文件 | `--check` 报坏引用；`--fix-refs`（dry-run）不动它；`--yes` 把它**重命名**到项目外 |
| 任意一次 dry-run | 对 `.git` 做逐文件指纹比对，**必须完全一致** |

最后一条是这套测试的核心：dry-run 的安全性用"文件指纹没变"来证明，
而不是靠"看输出里有没有 dry-run 字样"。

另外，`--fix-refs --yes` 那条用例还有一层意义：实测 `git update-ref -d <坏引用>`
对内容损坏的引用**会失败**（`cannot lock ref … reference broken`），
脚本必须走"重命名隔离"兜底才真的修得掉 —— 这条路径不测就会变成死代码。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

DOCTOR = Path(__file__).resolve().parents[2] / "scripts" / "doctor.py"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败：{proc.stderr}"
    return proc


def run_doctor(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """用真实进程跑 doctor.py（这样退出码与 stdout 都是可验证的）。"""
    return subprocess.run(
        [sys.executable, str(DOCTOR), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(repo),
    )


def git_fingerprint(git_dir: Path) -> dict[str, str]:
    """`.git` 里每个文件的 sha1 指纹。

    ⚠️ 故意**跳过 `.git/index`**：只读的 git 命令（status/fsck…）可能刷新
    index 的 stat 缓存并重写它，这不算"doctor 改了东西"。index 之外的文件
    一律必须逐字节不变。
    """
    fingerprint: dict[str, str] = {}
    for base, _dirs, files in os.walk(git_dir):
        for name in files:
            path = Path(base) / name
            rel = path.relative_to(git_dir).as_posix()
            if rel == "index":
                continue
            try:
                digest = hashlib.sha1(path.read_bytes()).hexdigest()
            except OSError:
                digest = "<unreadable>"
            fingerprint[rel] = digest
    return fingerprint


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """一个干净的小仓库：main 分支 + 2 个已提交文件，没有远程。"""
    root = tmp_path / "demo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "doctor@example.com")
    _git(root, "config", "user.name", "doctor-test")
    _git(root, "config", "core.autocrlf", "false")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "b.md").write_text("b\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def break_refs(repo: Path) -> Path:
    """把 .git/refs 整目录**改名**移走（模拟 rebase 触发的真实故障，不删文件）。"""
    refs = repo / ".git" / "refs"
    moved = repo / ".git" / "refs.moved-by-test"
    os.rename(refs, moved)
    return moved


# ---------------------------------------------------------------------------
# 用例 1：健康仓库
# ---------------------------------------------------------------------------


def test_check_healthy_repo_exits_zero(repo: Path) -> None:
    proc = run_doctor(repo, "--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr

    for keyword in (
        "仓库识别",
        "refs 目录结构完整",
        "没有坏引用",
        "HEAD 指向有效提交",
        "--connectivity-only 通过",
        "index.lock",
        "工作区文件完整",
        "当前分支",
        ".git 体积",
        "总判定",
        "健康",
    ):
        assert keyword in proc.stdout, f"输出里缺少检查项：{keyword}\n{proc.stdout}"


def _without_timestamp(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if "时间" not in line)


def test_check_is_the_default_action(repo: Path) -> None:
    """不加任何子命令时，行为必须等同 --check（默认只读）。"""
    without_args = run_doctor(repo)
    with_check = run_doctor(repo, "--check")
    assert without_args.returncode == with_check.returncode == 0
    assert _without_timestamp(without_args.stdout) == _without_timestamp(with_check.stdout)


# ---------------------------------------------------------------------------
# 用例 2：.git/refs 缺失（本机高发故障）
# ---------------------------------------------------------------------------


def test_check_reports_missing_refs(repo: Path) -> None:
    moved = break_refs(repo)
    assert moved.is_dir(), "前置条件：refs 已被改名移走"

    proc = run_doctor(repo, "--check")
    assert proc.returncode == 1, proc.stdout
    assert "refs 目录缺失" in proc.stdout
    assert "缺失" in proc.stdout
    # 提示里必须给出下一步命令
    assert "--fix-refs" in proc.stdout


def test_fix_refs_dry_run_when_refs_missing_keeps_everything(repo: Path) -> None:
    """重量路径（refs 结构缺失）的 dry-run 必须零副作用。"""
    _git(repo, "remote", "add", "origin", "https://example.invalid/demo.git")
    break_refs(repo)
    before = git_fingerprint(repo / ".git")

    proc = run_doctor(repo, "--fix-refs")
    assert proc.returncode == 0, proc.stdout
    assert "重量修复" in proc.stdout
    assert "dry-run" in proc.stdout
    assert not (repo / ".git" / "refs").exists(), "dry-run 不许重建 refs"
    assert git_fingerprint(repo / ".git") == before


def test_fix_refs_yes_restores_refs_from_local_remote(tmp_path: Path) -> None:
    """重量路径的**真实恢复**：用一个本地 bare 仓库当 origin，全程离线可复现。

    这条用例覆盖了最容易写错的两点：
    · refs 缺失时仓库内**所有** git 命令都会 fatal（连 git config 都不行），
      所以脚本必须直接读 .git/config 拿 url、在仓库外跑 ls-remote <url>；
    · 恢复顺序必须是「写回本地引用 → fetch → read-tree → reset --mixed → fsck」。
    """
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    repo = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(repo))
    _git(repo, "config", "user.email", "doctor@example.com")
    _git(repo, "config", "user.name", "doctor-test")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "push", "-q", "-u", "origin", "main")

    break_refs(repo)
    assert run_doctor(repo, "--check").returncode == 1
    # 前置条件：refs 没了以后，仓库内 git 命令确实全废
    broken_probe = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert broken_probe.returncode != 0

    proc = run_doctor(repo, "--fix-refs", "--yes")
    assert proc.returncode == 0, proc.stdout
    assert (repo / ".git" / "refs" / "heads" / "main").is_file()
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    assert run_doctor(repo, "--check").returncode == 0, run_doctor(repo, "--check").stdout


# ---------------------------------------------------------------------------
# 用例 3：已跟踪文件在磁盘上缺失
# ---------------------------------------------------------------------------


def test_missing_tracked_file_detected_and_restored_with_yes(repo: Path) -> None:
    parked = repo / "a.txt.parked-by-test"
    os.rename(repo / "a.txt", parked)

    checked = run_doctor(repo, "--check")
    assert checked.returncode == 1
    assert "a.txt" in checked.stdout
    assert "缺失" in checked.stdout

    # dry-run：先打印清单，绝不动文件
    dry = run_doctor(repo, "--restore")
    assert dry.returncode == 0, dry.stdout
    assert "a.txt" in dry.stdout
    assert "dry-run" in dry.stdout
    assert not (repo / "a.txt").exists(), "dry-run 不许恢复文件"
    assert parked.exists(), "dry-run 不许动被移走的文件"

    # --yes 才真的恢复
    real = run_doctor(repo, "--restore", "--yes")
    assert real.returncode == 0, real.stdout
    assert (repo / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert run_doctor(repo, "--check").returncode == 0


# ---------------------------------------------------------------------------
# 用例 4：坏引用
# ---------------------------------------------------------------------------


def test_bad_ref_detected_and_quarantined_by_yes(repo: Path) -> None:
    broken = repo / ".git" / "refs" / "heads" / "broken"
    broken.write_text("garbage-not-a-sha\n", encoding="ascii")

    checked = run_doctor(repo, "--check")
    assert checked.returncode == 1
    assert "坏引用" in checked.stdout
    assert "refs/heads/broken" in checked.stdout

    # dry-run 不许碰它
    dry = run_doctor(repo, "--fix-refs")
    assert dry.returncode == 0, dry.stdout
    assert "dry-run" in dry.stdout
    assert broken.exists(), "dry-run 不许动坏引用"

    # --yes：update-ref -d 会失败，脚本走重命名隔离兜底
    real = run_doctor(repo, "--fix-refs", "--yes")
    assert real.returncode == 0, real.stdout
    assert not broken.exists()

    quarantine = list(repo.parent.glob(f"{repo.name}_broken_refs_*"))
    moved = [d for d in quarantine if (d / "refs" / "heads" / "broken").is_file()]
    assert moved, f"坏引用应被重命名到项目外，实际隔离目录：{quarantine}"
    assert (moved[0] / "refs" / "heads" / "broken").read_text(encoding="ascii") == (
        "garbage-not-a-sha\n"
    )

    assert run_doctor(repo, "--check").returncode == 0


# ---------------------------------------------------------------------------
# 用例 5：--fix-refs 的 dry-run 完全只读
# ---------------------------------------------------------------------------


def test_fix_refs_without_yes_changes_nothing(repo: Path) -> None:
    _git(repo, "remote", "add", "origin", "https://example.invalid/demo.git")
    broken = repo / ".git" / "refs" / "heads" / "broken"
    broken.write_text("garbage-not-a-sha\n", encoding="ascii")
    before = git_fingerprint(repo / ".git")

    proc = run_doctor(repo, "--fix-refs")
    assert proc.returncode == 0, proc.stdout
    assert "dry-run" in proc.stdout
    assert "--yes" in proc.stdout
    assert git_fingerprint(repo / ".git") == before, "dry-run 改动了 .git 里的文件"
    assert broken.read_text(encoding="ascii") == "garbage-not-a-sha\n"


# ---------------------------------------------------------------------------
# 用例 6：--backup-git
# ---------------------------------------------------------------------------


def test_backup_git_copies_every_file(repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "git-backup"

    proc = run_doctor(repo, "--backup-git", "--dest", str(dest))
    assert proc.returncode == 0, proc.stdout
    assert str(dest) in proc.stdout
    assert dest.is_dir()

    src_files = sorted(p.relative_to(repo / ".git").as_posix() for p in (repo / ".git").rglob("*"))
    dst_files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*"))
    assert dst_files == src_files
    assert len(dst_files) > 0
    assert "文件数校验" in proc.stdout


def test_backup_git_refuses_dest_inside_project(repo: Path) -> None:
    inside = repo / "backup-inside"
    proc = run_doctor(repo, "--backup-git", "--dest", str(inside))
    assert proc.returncode == 1
    assert "项目内" in proc.stdout
    assert not inside.exists()
