#!/usr/bin/env python
"""`.git` 体检 + 安全恢复（归属：全队共用 / Issue #20 P1）。

## 为什么需要它

本仓库在这台机器上**反复出现 git 损坏**，每次都靠现场回忆步骤来救：

| 现象 | 现在怎么救 |
|---|---|
| `.git/refs/` 被删 → 所有 git 命令报 `not a git repository`（`git rebase` 稳定触发，已复现 2 次） | 重建 `refs/` 目录 + 用远端权威 sha 写回分支引用 + `read-tree`/`reset` |
| `cannot lock ref` / `unable to resolve reference`，`git diff` 给出假结果 | `git update-ref -d <坏引用>` → `git remote prune origin` → `git fetch` |
| 工作区已跟踪文件在磁盘上缺失（`git status` 显示 ` D`） | `git restore .` |
| `.git/index.lock` 移不走 / git 进程卡死 | 查进程 → 杀 → 重命名移锁（不是删） |

这个脚本把这些**变回一条命令**，并且把"哪些是只读、哪些会改东西"写死进默认值。

## 四个子命令

```bash
# ① 体检（默认动作，纯只读，不改任何东西）
python scripts/doctor.py
python scripts/doctor.py --check

# ② 修 refs 类故障（默认 **dry-run**，只打印将执行的命令）
python scripts/doctor.py --fix-refs            # 先看要跑什么
python scripts/doctor.py --fix-refs --yes      # 确认后才真的执行

# ③ 恢复"已跟踪但磁盘缺失"的文件（同样默认 dry-run）
python scripts/doctor.py --restore
python scripts/doctor.py --restore --yes

# ④ 把 .git 备份到**项目外**（可用 --dest 指定目录）
python scripts/doctor.py --backup-git
python scripts/doctor.py --backup-git --dest D:/git_backups/xizhi-0918
```

其它参数：`--repo <路径>`（默认当前目录向上找 `.git`）。

## 安全约定（重要）

1. **`--check` 是只读的**，不创建/不修改/不删除任何东西。
2. **`--fix-refs` / `--restore` 默认 dry-run**：只打印将要执行的命令与文件清单，
   必须显式加 `--yes` 才会真正执行。没有 `--yes` 时**保证零副作用**。
3. 两个破坏性动作执行前都会打印横幅提醒：**"已备份 `.git` ？"**
   —— 不确定就先 `--backup-git`，它默认写到**项目外**，不会污染仓库。
4. 本脚本**永远不会**执行 `rebase` / `clean` / `reset --hard`，也**不删除任何文件**：
   移锁、移文件一律提示用"重命名到项目外"。
5. 本脚本唯一直接写盘的两处：`--fix-refs` 的重量路径**新建** `.git/refs/**`
   引用文件（内容取自 `git ls-remote origin` 的权威 sha）；轻量路径在
   `git update-ref -d` 失败时，把坏引用**文件重命名**到项目外的隔离目录
   `../<仓库名>_broken_refs_<时间戳>/`（保留内容，可随时改名复原）。

> 实测记录（2026-09-18，git 2.47.1.windows.1）：对内容损坏的引用，
> `git update-ref -d <坏引用>` 会报
> `cannot lock ref … unable to resolve reference … reference broken` —— **删不掉**。
> 所以本工具的轻量路径带"重命名隔离"兜底，否则那条 `update-ref -d` 只是好看。

退出码：健康 `0`；有问题 `1`（`--fix-refs` / `--restore` 的 dry-run 视为成功，返回 `0`）。
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

OK = "✅"
WARN = "⚠️"
FAIL = "❌"

# 必须存在的 refs 目录（本机高发故障：整个 .git/refs 被删）
REQUIRED_REFS_DIRS = ("refs", "refs/heads", "refs/tags")

BACKUP_REMINDER = (
    "⚠️  执行前请确认：已备份 .git ？"
    "（不确定就先跑 python scripts/doctor.py --backup-git，默认写到项目外）"
)

GIT_TIMEOUT = 120
GIT_SLOW_TIMEOUT = 300


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


@dataclass
class GitResult:
    """一次 git 调用的结果（永不抛异常，失败信息都在字段里）。"""

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def error_line(self) -> str:
        """取一条最能说明问题的输出行（stderr 优先）。"""
        for text in (self.stderr, self.stdout):
            for line in (text or "").splitlines():
                if line.strip():
                    return line.strip()
        return f"git 退出码 {self.returncode}"

    def command(self) -> str:
        return " ".join(shlex.quote(part) for part in self.argv)


def git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> GitResult:
    """调用 git（不抛异常；超时/找不到 git 也退化成错误结果）。"""
    argv = ["git", "-C", str(repo), *args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return GitResult(argv, 124, "", f"命令超时（>{timeout}s），网络类命令可先试：git config http.sslBackend openssl")
    except OSError as exc:  # git 不在 PATH 等
        return GitResult(argv, 127, "", str(exc))
    return GitResult(argv, proc.returncode, proc.stdout, proc.stderr)


def git_outside_repo(*args: str, timeout: int = GIT_SLOW_TIMEOUT) -> GitResult:
    """在**仓库外**调用 git。

    `.git/refs` 一缺，仓库内的所有 git 命令（含 `git config`、甚至
    `git --git-dir=... rev-parse`）都会 fatal: not a git repository。
    但 `git ls-remote <url>` 不依赖本地仓库，所以在系统 temp 里跑它仍能拿到权威 sha。
    """
    argv = ["git", *args]
    workdir = tempfile.gettempdir()
    try:
        proc = subprocess.run(
            argv,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return GitResult(argv, 124, "", f"命令超时（>{timeout}s），网络类命令可先试：git config http.sslBackend openssl")
    except OSError as exc:
        return GitResult(argv, 127, "", str(exc))
    return GitResult(argv, proc.returncode, proc.stdout, proc.stderr)


def find_repo_and_git_dir(start: Path) -> tuple[Path | None, Path | None]:
    """向上查找 .git（**不依赖 git 命令**，refs 被删时 git 全报 not a repository）。

    返回 (仓库根, .git 目录)；找不到时对应项为 None。
    """
    try:
        current = start.resolve()
    except OSError:
        return None, None
    for base in (current, *current.parents):
        candidate = base / ".git"
        if candidate.is_dir():
            return base, candidate
        if candidate.is_file():  # worktree / submodule：内容是 `gitdir: <路径>`
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = re.match(r"\s*gitdir:\s*(.+)", text)
            if match:
                git_dir = Path(match.group(1).strip())
                if not git_dir.is_absolute():
                    git_dir = (base / git_dir).resolve()
                return base, git_dir
    return None, None


def dir_size(root: Path) -> int:
    """递归统计目录体积（出错就跳过，不抛）。"""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def count_files(root: Path) -> int:
    total = 0
    for _dirpath, _dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        total += len(filenames)
    return total


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


@dataclass
class Item:
    status: str
    title: str
    detail: str = ""
    hint: str = ""


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)

    def add(self, status: str, title: str, detail: str = "", hint: str = "") -> None:
        self.items.append(Item(status, title, detail, hint))

    def ok(self, title: str, detail: str = "") -> None:
        self.add(OK, title, detail)

    def problem_count(self, status: str) -> int:
        return sum(1 for item in self.items if item.status == status)

    @property
    def healthy(self) -> bool:
        return self.problem_count(FAIL) == 0 and self.problem_count(WARN) == 0

    def render(self) -> None:
        for item in self.items:
            line = f"{item.status} {item.title}"
            if item.detail:
                line += f"\n      {item.detail}"
            print(line)
            if item.hint:
                print(f"      → {item.hint}")
        print("─" * 64)
        if self.healthy:
            print(f"总判定：{OK} 健康（{len(self.items)} 项检查未发现问题）")
        else:
            print(
                f"总判定：{FAIL} 有问题 —— ❌ {self.problem_count(FAIL)} 项 / "
                f"⚠️ {self.problem_count(WARN)} 项（共 {len(self.items)} 项检查）"
            )
        hints: list[str] = []
        for item in self.items:
            if item.status in (FAIL, WARN) and item.hint and item.hint not in hints:
                hints.append(item.hint)
        if hints:
            print("\n建议执行的下一步：")
            for index, hint in enumerate(hints, start=1):
                print(f"  {index}. {hint}")


@dataclass
class Ctx:
    """一次运行的上下文。"""

    repo_arg: Path
    repo: Path
    git_dir: Path | None = None
    refs_missing: bool = False
    git_usable: bool = False


def build_ctx(repo_arg: Path) -> Ctx:
    repo, git_dir = find_repo_and_git_dir(repo_arg)
    ctx = Ctx(repo_arg=repo_arg, repo=repo or repo_arg, git_dir=git_dir)
    return ctx


def print_header(title: str, ctx: Ctx) -> None:
    print("=" * 64)
    print(f" xizhi doctor · {title}")
    print(f" 调用目录：{ctx.repo_arg}")
    print(f" 仓库根　：{ctx.repo}")
    print(f" git 目录：{ctx.git_dir if ctx.git_dir else '（未找到 .git）'}")
    print(f" 时间　　：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 64)


# ---------------------------------------------------------------------------
# 各项检查（只读）
# ---------------------------------------------------------------------------


def check_repo(ctx: Ctx, report: Report) -> None:
    if ctx.git_dir is None:
        report.add(
            FAIL,
            "仓库识别：未找到 .git",
            f"从 {ctx.repo_arg} 向上都没找到 .git 目录或 gitdir 文件",
            "用 --repo <路径> 指定仓库根目录后重试",
        )
        return
    report.ok("仓库识别：找到 .git", str(ctx.git_dir))

    result = git(ctx.repo, "rev-parse", "--is-inside-work-tree")
    ctx.git_usable = result.ok
    if result.ok:
        report.ok("git 可用：rev-parse --is-inside-work-tree", result.stdout.strip())
    else:
        report.add(
            FAIL,
            "git 不可用：几乎所有 git 命令都会失败",
            result.error_line(),
            "若报 'not a git repository' 且 .git/refs 缺失 → python scripts/doctor.py --fix-refs",
        )


def check_refs(ctx: Ctx, report: Report) -> None:
    git_dir = ctx.git_dir
    assert git_dir is not None

    missing = [name for name in REQUIRED_REFS_DIRS if not (git_dir / name).is_dir()]
    if "refs" in missing:
        ctx.refs_missing = True
        report.add(
            FAIL,
            ".git/refs 目录缺失 ← 本机高发故障",
            "缺失：" + "、".join(missing) + f"（在 {git_dir} 下）",
            "复现机制：git rebase 可稳定触发。修复：python scripts/doctor.py --fix-refs（先看）→ 加 --yes 执行",
        )
        return

    if missing:
        report.add(
            FAIL,
            "refs 子目录缺失",
            "缺失：" + "、".join(missing),
            "修复：python scripts/doctor.py --fix-refs（dry-run）→ 加 --yes 执行",
        )
    else:
        report.ok("refs 目录结构完整", "、".join(REQUIRED_REFS_DIRS))

    if (git_dir / "refs/remotes/origin").is_dir():
        report.ok("refs/remotes/origin 存在")
    else:
        url = git(ctx.repo, "config", "--get", "remote.origin.url")
        if url.ok and url.stdout.strip():
            report.add(
                WARN,
                "refs/remotes/origin 缺失",
                f"已配置 origin={url.stdout.strip()}，但没有远程跟踪引用",
                "git remote prune origin && git fetch origin",
            )
        else:
            report.ok("refs/remotes/origin 不适用", "（未配置 origin 远程，跳过）")


def check_head(ctx: Ctx, report: Report) -> None:
    git_dir = ctx.git_dir
    assert git_dir is not None
    symref: str | None = None
    head_file = git_dir / "HEAD"
    if head_file.is_file():
        content = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if content.startswith("ref: "):
            symref = content[len("ref: ") :].strip()

    result = git(ctx.repo, "rev-parse", "--verify", "HEAD")
    if result.ok:
        sha = result.stdout.strip()
        where = f"（{symref}）" if symref else "（detached HEAD）"
        report.ok("HEAD 指向有效提交", f"{sha[:12]} {where}")
        return

    if symref and not ctx.refs_missing:
        target_exists = (git_dir / symref).exists()
        packed = git_dir / "packed-refs"
        in_packed = (
            symref in packed.read_text(encoding="utf-8", errors="replace")
            if packed.is_file()
            else False
        )
        if not target_exists and not in_packed:
            report.ok("HEAD 尚未指向提交", f"（{symref} 还不存在，仓库可能还没有任何提交）")
            return

    report.add(
        FAIL,
        "HEAD 无法解析出提交",
        result.error_line(),
        "若同时报 .git/refs 缺失，用 --fix-refs；否则检查 .git/HEAD 的内容",
    )


def check_fsck(ctx: Ctx, report: Report) -> None:
    result = git(ctx.repo, "fsck", "--connectivity-only", "--no-progress", timeout=GIT_SLOW_TIMEOUT)
    if result.ok:
        first = next((line for line in result.stdout.splitlines() if line.strip()), "")
        report.ok("git fsck --connectivity-only 通过", first or "（无输出）")
    else:
        report.add(
            FAIL,
            "git fsck --connectivity-only 失败",
            result.error_line(),
            "若同时报了坏引用，先用 --fix-refs；否则对象库可能损坏：先 --backup-git 保留现场再贴报错",
        )


def index_lock_state(lock: Path) -> str:
    """探测锁文件是否**真被占用**（只看文件存在会误报）。"""
    try:
        handle = os.open(str(lock), os.O_RDWR)
    except OSError:
        return "held"
    os.close(handle)
    return "stale"


def check_index_lock(ctx: Ctx, report: Report) -> None:
    git_dir = ctx.git_dir
    assert git_dir is not None
    lock = git_dir / "index.lock"
    if not lock.exists():
        report.ok(".git/index.lock 不存在", "（没有残留锁）")
        return

    if index_lock_state(lock) == "held":
        report.add(
            FAIL,
            ".git/index.lock 被真实占用",
            "文件存在且无法以读写方式打开 → 很可能有 git 进程正在运行",
            "先查进程再结束：tasklist | findstr git（bash: ps -W | grep git），然后重新体检",
        )
    else:
        report.add(
            WARN,
            ".git/index.lock 是残留锁（未被占用）",
            "文件存在但可正常打开写入 → 大概率是上次 git 异常退出留下的",
            "移走而不是删除：mv <repo>/.git/index.lock <项目外>（本脚本不代删）",
        )


def list_missing_tracked(ctx: Ctx) -> tuple[list[str], int]:
    """返回 (磁盘上缺失的已跟踪文件, 已跟踪文件总数)；git 不可用时总数为 -1。"""
    result = git(ctx.repo, "ls-files", "-z")
    if not result.ok:
        return [], -1
    tracked = [path for path in result.stdout.split("\0") if path]
    missing = sorted(path for path in tracked if not os.path.lexists(ctx.repo / path))
    return missing, len(tracked)


def check_missing_files(ctx: Ctx, report: Report) -> list[str]:
    missing, tracked_total = list_missing_tracked(ctx)
    if tracked_total < 0:
        report.add(
            FAIL,
            "无法列出已跟踪文件",
            "git ls-files 执行失败",
            "先按上面的 refs 问题修复，再重新体检",
        )
        return []
    if missing:
        shown = "、".join(missing[:20])
        if len(missing) > 20:
            shown += f" …（共 {len(missing)} 个）"
        report.add(
            FAIL,
            f"工作区有 {len(missing)} 个已跟踪文件在磁盘上缺失",
            shown,
            "python scripts/doctor.py --restore（先看清单）→ 加 --yes 执行",
        )
    else:
        report.ok("工作区文件完整", f"已跟踪 {tracked_total} 个文件，全部在磁盘上")
    return missing


def _current_branch(ctx: Ctx) -> str | None:
    result = git(ctx.repo, "symbolic-ref", "--short", "-q", "HEAD")
    if result.ok and result.stdout.strip():
        return result.stdout.strip()
    return None


BROKEN_REF_RE = re.compile(r"ignoring broken ref (\S+)")


def _all_ref_names(ctx: Ctx) -> list[str]:
    """枚举"真实存在"的引用名（refs/ 下的文件 + packed-refs）。"""
    git_dir = ctx.git_dir
    assert git_dir is not None
    names: list[str] = []
    refs_root = git_dir / "refs"
    if refs_root.is_dir():
        for path in sorted(refs_root.rglob("*")):
            if path.is_file():
                names.append(path.relative_to(git_dir).as_posix())
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("^"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                names.append(parts[1].strip())
    return list(dict.fromkeys(names))


def scan_broken_refs_fast(ctx: Ctx) -> list[str]:
    """快速扫描：git for-each-ref 会把坏引用以 warning 打到 stderr（实测 rc 仍是 0）。"""
    result = git(ctx.repo, "for-each-ref", "--format=%(refname)")
    return list(dict.fromkeys(BROKEN_REF_RE.findall(result.stderr or "")))


def scan_broken_refs_thorough(ctx: Ctx) -> list[str]:
    """彻底扫描：逐个 show-ref --verify 验证（慢但不会漏，for-each-ref 会静默忽略坏引用）。"""
    broken: list[str] = []
    for name in _all_ref_names(ctx):
        if not git(ctx.repo, "show-ref", "--verify", "--quiet", name).ok:
            broken.append(name)
    return broken


def check_bad_refs(ctx: Ctx, report: Report) -> None:
    if not ctx.git_usable or ctx.refs_missing:
        report.ok("坏引用检查不适用", "（refs 结构缺失或 git 不可用，已在上面报出）")
        return
    broken = scan_broken_refs_fast(ctx)
    if broken:
        report.add(
            FAIL,
            f"发现 {len(broken)} 个坏引用（会让 git diff 等命令给出假结果）",
            "、".join(broken),
            "python scripts/doctor.py --fix-refs（先看要执行什么）→ 加 --yes 执行",
        )
    else:
        report.ok("没有坏引用", "for-each-ref 未报 'ignoring broken ref'")


def check_branches(ctx: Ctx, report: Report) -> None:
    branch = _current_branch(ctx)
    if branch:
        report.ok("当前分支", branch)
    else:
        short = git(ctx.repo, "rev-parse", "--short", "HEAD")
        report.ok("当前处于 detached HEAD", short.stdout.strip() or "（无法解析）")

    upstream_res = git(ctx.repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    upstream = upstream_res.stdout.strip() if upstream_res.ok else ""
    if not upstream:
        report.ok("ahead/behind 不适用", "（当前分支未设置 upstream，或没有远程）")
    else:
        counts = git(ctx.repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        parts = counts.stdout.split()
        if counts.ok and len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])
            if behind:
                report.add(
                    WARN,
                    f"落后 {upstream} {behind} 个提交",
                    f"ahead {ahead} / behind {behind}",
                    "用 git pull --ff-only 拉取；⚠️ 不要用 git rebase（本机会破坏 .git/refs）",
                )
            else:
                report.ok("与 upstream 同步", f"ahead {ahead} / behind {behind}（{upstream}）")
        else:
            report.add(
                WARN,
                "无法计算 ahead/behind",
                counts.error_line(),
                "引用可能已损坏 → python scripts/doctor.py --fix-refs",
            )

    base: str | None = None
    head_ref = git(ctx.repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if head_ref.ok and head_ref.stdout.strip():
        base = head_ref.stdout.strip()
    else:
        for candidate in ("origin/main", "origin/master"):
            if git(ctx.repo, "rev-parse", "--verify", "--quiet", candidate).ok:
                base = candidate
                break
    if base is None:
        base = branch
    if base is None:
        report.ok("已合并分支检查不适用", "（无法确定基线分支）")
        return

    merged_res = git(ctx.repo, "branch", "--merged", base, "--format=%(refname:short)")
    if not merged_res.ok:
        report.add(
            WARN,
            "无法列出已合并分支",
            merged_res.error_line(),
            f"手工检查：git branch --merged {base}",
        )
        return
    merged = [line.strip() for line in merged_res.stdout.splitlines() if line.strip()]
    keep = {branch, base, "main", "master", base.split("/")[-1]}
    stale = [name for name in merged if name not in keep]
    if stale:
        report.add(
            WARN,
            f"有 {len(stale)} 个已合并但未删除的本地分支",
            "、".join(stale),
            "逐个确认内容已进主干后再删：git branch -d <分支>",
        )
    else:
        report.ok("没有已合并却未删除的本地分支", f"（基线 {base}）")


def check_venv(ctx: Ctx, report: Report) -> None:
    venv = ctx.repo / "backend" / ".venv"
    if not os.path.lexists(venv):
        report.ok("backend/.venv 不适用", "（未找到，跳过）")
        return

    is_junction = getattr(os.path, "isjunction", None)
    is_link = os.path.islink(venv) or bool(is_junction and is_junction(venv))
    real = Path(os.path.realpath(venv))
    inside = real.is_relative_to(ctx.repo)
    kind = "链接" if is_link else "真实目录"

    if inside:
        report.add(
            WARN,
            "backend/.venv 落在项目内（有被清理程序清空的风险）",
            f"{kind} → {real}",
            "移出项目重建：python -m venv %USERPROFILE%\\.venvs\\xizhi-backend，"
            "再把 backend/.venv 改为指向它的联接（参考 scripts/setup-venv.sh）",
        )
    else:
        report.ok(f"backend/.venv 是{kind}且指向项目外", str(real))


def check_stats(ctx: Ctx, report: Report) -> None:
    git_dir = ctx.git_dir
    assert git_dir is not None
    size = dir_size(git_dir)
    count = count_files(git_dir)
    report.ok(".git 体积", f"{human_size(size)}（{count} 个文件）")
    if not ctx.git_usable:
        return
    log = git(ctx.repo, "log", "-1", "--date=short", "--format=%h %ad %s")
    if log.ok and log.stdout.strip():
        report.ok("最近一次提交", log.stdout.strip())


# ---------------------------------------------------------------------------
# ① --check
# ---------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    ctx = build_ctx(Path(args.repo))
    print_header("体检（只读）", ctx)
    print("说明：本模式只读，不会修改、创建或删除任何东西。\n")

    report = Report()
    if ctx.git_dir is None:
        check_repo(ctx, report)
    else:
        check_repo(ctx, report)
        check_refs(ctx, report)
        if ctx.git_dir is not None:
            check_bad_refs(ctx, report)
        check_head(ctx, report)
        check_fsck(ctx, report)
        check_index_lock(ctx, report)
        check_missing_files(ctx, report)
        check_branches(ctx, report)
        check_venv(ctx, report)
        check_stats(ctx, report)

    report.render()
    return 0 if report.healthy else 1


# ---------------------------------------------------------------------------
# ② --fix-refs
# ---------------------------------------------------------------------------


def current_branch_name(ctx: Ctx) -> str | None:
    if ctx.git_dir is None:
        return None
    head_file = ctx.git_dir / "HEAD"
    if not head_file.is_file():
        return None
    content = head_file.read_text(encoding="utf-8", errors="replace").strip()
    prefix = "ref: refs/heads/"
    if content.startswith(prefix):
        return content[len(prefix) :].strip()
    return None


def collect_bad_refs(ctx: Ctx) -> list[str]:
    """供 --fix-refs 使用：逐个验证引用（慢但不会漏）。"""
    return scan_broken_refs_thorough(ctx)


def quarantine_root_for(ctx: Ctx) -> Path:
    """坏引用文件的隔离目录（项目外，重命名进去而不是删除）。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return ctx.repo.parent / f"{ctx.repo.name}_broken_refs_{stamp}"


def quarantine_broken_refs(ctx: Ctx, refs: list[str], dest_root: Path) -> tuple[list[str], list[str]]:
    """把坏引用的**文件**重命名到项目外（保留内容，不删除）。

    返回 (已移走, 移不动的)。
    """
    git_dir = ctx.git_dir
    assert git_dir is not None
    moved: list[str] = []
    stuck: list[str] = []
    for ref in refs:
        source = git_dir / ref
        if not source.is_file():
            stuck.append(ref)
            continue
        target = dest_root / ref
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except (OSError, shutil.Error) as exc:
            print(f"      {FAIL} 移不动 {ref}：{exc}")
            stuck.append(ref)
            continue
        moved.append(ref)
        print(f"  {OK} {source} → {target}")
    return moved, stuck


def _fix_refs_light(ctx: Ctx, args: argparse.Namespace, report: Report) -> int:
    bad = collect_bad_refs(ctx)
    branch = current_branch_name(ctx)
    unsafe = [ref for ref in bad if branch and ref == f"refs/heads/{branch}"]
    safe = [ref for ref in bad if ref not in unsafe]

    if not bad:
        report.ok("未发现坏引用", "refs/ 下的引用与 packed-refs 都能解析")
        report.ok("无需修复", "若仍报 cannot lock ref / unable to resolve reference，请把原文贴到 Issue")
        report.render()
        return 0

    steps: list[list[str]] = [["update-ref", "-d", ref] for ref in safe]
    has_origin = remote_origin_url(ctx) is not None
    if has_origin:
        steps.append(["remote", "prune", "origin"])
        steps.append(["fetch", "origin"])
    steps.append(["fsck", "--connectivity-only", "--no-progress"])
    quarantine = quarantine_root_for(ctx)

    if unsafe:
        report.add(
            WARN,
            "跳过当前分支的坏引用（危险，不自动动它）",
            "、".join(unsafe),
            "当前分支引用损坏需人工处理：确认远端 sha 后手工 git update-ref refs/heads/<分支> <sha>",
        )
    report.ok(f"待处理坏引用：{len(bad)} 个", "、".join(bad))

    print_plan(ctx, steps)
    print(
        "\n注意：实测 `git update-ref -d <坏引用>` 对内容损坏的引用会失败\n"
        "      （报 cannot lock ref / unable to resolve reference / reference broken）。\n"
        "      脚本的兜底动作是把坏引用的**文件重命名**到项目外（保留内容，不删除）：\n"
        f"      {quarantine}"
    )

    if not args.yes:
        print("\n（dry-run：以上命令**均未执行**，没有任何改动。确认无误后加 --yes）")
        report.ok("dry-run 完成", "未修改任何东西")
        report.render()
        return 1 if unsafe else 0

    print("\n开始执行：")
    failed: list[str] = []
    for ref in safe:
        result = git(ctx.repo, "update-ref", "-d", ref, timeout=GIT_SLOW_TIMEOUT)
        if result.ok:
            print(f"  {OK} git update-ref -d {ref}")
        else:
            print(f"  {WARN} git update-ref -d {ref} → {result.error_line()}")
            failed.append(ref)

    remaining = collect_bad_refs(ctx)
    if remaining:
        print(f"\n  {WARN} 仍有 {len(remaining)} 个坏引用删不掉，走重命名兜底：")
        moved, stuck = quarantine_broken_refs(ctx, remaining, quarantine)
        if moved:
            report.ok("坏引用已隔离到项目外", f"{'、'.join(moved)} → {quarantine}")
        if stuck:
            report.add(
                FAIL,
                f"还有 {len(stuck)} 个坏引用动不了",
                "、".join(stuck),
                "这些引用只在 packed-refs 里：需人工编辑 .git/packed-refs（先备份 .git）",
            )
    elif failed:
        report.ok("坏引用已通过 git update-ref -d 删除", "、".join(failed))

    follow_up: list[list[str]] = []
    if has_origin:
        follow_up = [
            ["remote", "prune", "origin"],
            ["fetch", "origin"],
        ]
    follow_up.append(["fsck", "--connectivity-only", "--no-progress"])
    print("\n继续执行：")
    failures = run_steps(ctx, follow_up)
    still_broken = collect_bad_refs(ctx)
    if failures or still_broken:
        report.add(
            FAIL,
            "修复未完全成功",
            f"仍有坏引用：{'、'.join(still_broken)}" if still_broken else "命令有失败（见上）",
            f"把输出贴到 Issue；坏引用文件已隔离在 {quarantine}（可随时改名复原）",
        )
        report.render()
        return 1
    report.ok("修复完成", "坏引用已处理，prune/fetch/fsck 均通过")
    report.ok("复查", "python scripts/doctor.py --check")
    report.render()
    return 1 if unsafe else 0


def remote_origin_url(ctx: Ctx) -> str | None:
    """取 origin 的 url。

    先试 `git config`；失败就**直接解析 `.git/config`** —— 因为 refs 一坏，
    `git config` 也会报 not a git repository，而那正是最需要这个 url 的时候。
    """
    result = git(ctx.repo, "config", "--get", "remote.origin.url")
    if result.ok and result.stdout.strip():
        return result.stdout.strip()
    git_dir = ctx.git_dir
    if git_dir is None:
        return None
    config = git_dir / "config"
    if not config.is_file():
        return None
    section = ""
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section == 'remote "origin"' and re.match(r"url\s*=", line):
            return line.split("=", 1)[1].strip()
    return None


def parse_ls_remote(output: str) -> dict[str, str]:
    """解析 git ls-remote 的输出为 {refname: sha}。"""
    table: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and not parts[1].endswith("^{}"):
            table[parts[1]] = parts[0]
    return table


def local_branch_names(ctx: Ctx) -> list[str]:
    """能推断出的本地分支名（HEAD 的符号引用 + packed-refs）。"""
    git_dir = ctx.git_dir
    assert git_dir is not None
    found: list[str] = []
    head = current_branch_name(ctx)
    if head:
        found.append(head)
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            ref = parts[1].strip()
            if ref.startswith("refs/heads/"):
                found.append(ref[len("refs/heads/") :])
    return list(dict.fromkeys(name for name in found if name))


def print_plan(ctx: Ctx, steps: list[list[str]]) -> None:
    print(f"\n将要执行的命令（仓库：{ctx.repo}）：")
    for step in steps:
        print(f"  $ git -C {shlex.quote(str(ctx.repo))} " + " ".join(step))


def run_steps(ctx: Ctx, steps: list[list[str]]) -> int:
    failures = 0
    for step in steps:
        result = git(ctx.repo, *step, timeout=GIT_SLOW_TIMEOUT)
        mark = OK if result.ok else FAIL
        print(f"  {mark} git {' '.join(step)}")
        if not result.ok:
            failures += 1
            print(f"      {result.error_line()}")
            break
        output = result.stdout.strip()
        if output:
            for line in output.splitlines()[:5]:
                print(f"      {line}")
    return failures


def cmd_fix_refs(args: argparse.Namespace) -> int:
    ctx = build_ctx(Path(args.repo))
    print_header("修复 refs 类故障（默认 dry-run）", ctx)
    report = Report()

    if ctx.git_dir is None:
        report.add(FAIL, "未找到 .git", f"从 {ctx.repo_arg} 向上都没找到", "用 --repo 指定仓库根")
        report.render()
        return 1

    refs_broken = not (ctx.git_dir / "refs").is_dir() or any(
        not (ctx.git_dir / name).is_dir() for name in REQUIRED_REFS_DIRS
    )
    print(f"模式：{'重量修复（.git/refs 结构缺失）' if refs_broken else '轻量修复（删除坏引用 + 重新 fetch）'}")
    print(BACKUP_REMINDER)

    if refs_broken:
        return _fix_refs_heavy(ctx, args, report)
    return _fix_refs_light(ctx, args, report)


def _fix_refs_heavy(ctx: Ctx, args: argparse.Namespace, report: Report) -> int:
    git_dir = ctx.git_dir
    assert git_dir is not None

    url = remote_origin_url(ctx)
    if not url:
        report.add(
            FAIL,
            "无法重量修复：没有配置 origin 远程",
            "refs 结构已缺失，写回分支引用需要远端权威 sha（.git/config 里没有 remote.origin.url）",
            "先 git remote add origin <url>（或人工把 .git/packed-refs 里的 sha 写进 .git/refs/heads/<分支>）",
        )
        report.render()
        return 1

    branches = local_branch_names(ctx)
    if not branches:
        report.add(
            FAIL,
            "无法确定要恢复哪些分支",
            "HEAD 不是符号引用，packed-refs 里也没有 refs/heads/*",
            "人工确认分支名后，把 git ls-remote origin 的 sha 写进 .git/refs/heads/<分支>",
        )
        report.render()
        return 1

    plan_lines = [
        "mkdir -p .git/refs/heads .git/refs/tags .git/refs/remotes/origin",
        f"git ls-remote {url}          # 仓库外执行，取权威 sha",
        *[f"写 .git/refs/heads/{name} ← refs/heads/{name} 的 sha" for name in branches],
        "git fetch origin             # 先 fetch，保证对象都在本地",
        "git remote set-head origin --auto   # 补回 refs/remotes/origin/HEAD",
        "git read-tree HEAD",
        "git reset --mixed HEAD",
        "git fsck --connectivity-only --no-progress",
    ]
    print(f"\n将要执行的步骤（仓库：{ctx.repo}，origin={url}）：")
    for line in plan_lines:
        print(f"  · {line}")

    if not args.yes:
        print("\n（dry-run：以上步骤**均未执行**，.git 一个字节都没改。确认无误后加 --yes）")
        report.ok("dry-run 完成", f"未修改任何东西；待恢复分支：{'、'.join(branches)}")
        report.render()
        return 0

    for name in REQUIRED_REFS_DIRS + ("refs/remotes/origin",):
        (git_dir / name).mkdir(parents=True, exist_ok=True)
    print(f"\n{OK} 重建 refs 目录结构")

    # ⚠️ 必须用 `git ls-remote <url>` 在仓库外拿 sha：refs 缺失时仓库内任何
    #    git 命令（包括 git config / --git-dir）都会 fatal: not a git repository。
    remote = git_outside_repo("ls-remote", url)
    if not remote.ok:
        report.add(
            FAIL,
            "git ls-remote 失败，无法取得权威 sha",
            remote.error_line(),
            "网络类失败先试：git config http.sslBackend openssl；仍失败就把报错贴到 Issue",
        )
        report.render()
        return 1
    table = parse_ls_remote(remote.stdout)
    print(f"{OK} ls-remote 返回 {len(table)} 条引用")

    restored: list[str] = []
    for name in branches:
        sha = table.get(f"refs/heads/{name}")
        if not sha:
            print(f"  {WARN} 远端没有 refs/heads/{name}，跳过")
            continue
        ref_file = git_dir / "refs/heads" / name
        ref_file.parent.mkdir(parents=True, exist_ok=True)
        ref_file.write_text(sha + "\n", encoding="ascii")
        restored.append(name)
        print(f"  {OK} .git/refs/heads/{name} ← {sha[:12]}")
    if not restored:
        report.add(FAIL, "一个分支引用都没能写回", "远端没有匹配的分支名", "人工确认分支名后重试")
        report.render()
        return 1

    print("\n继续执行：")
    # fetch 放在 read-tree 之前：先保证对象在本地；但 fetch 失败不阻断本地恢复
    fetch = git(ctx.repo, "fetch", "origin", timeout=GIT_SLOW_TIMEOUT)
    if fetch.ok:
        print(f"  {OK} git fetch origin")
        head_set = git(ctx.repo, "remote", "set-head", "origin", "--auto", timeout=GIT_SLOW_TIMEOUT)
        mark = OK if head_set.ok else WARN
        print(f"  {mark} git remote set-head origin --auto")
    else:
        print(f"  {WARN} git fetch origin → {fetch.error_line()}")
        print("      （对象若都在本地，下面仍能恢复；网络问题可先 git config http.sslBackend openssl）")
    failures = run_steps(
        ctx,
        [
            ["read-tree", "HEAD"],
            ["reset", "--mixed", "HEAD"],
            ["fsck", "--connectivity-only", "--no-progress"],
        ],
    )
    if not fetch.ok:
        report.add(
            FAIL,
            "git fetch origin 失败（本地引用可能已恢复，但远端引用没刷新）",
            fetch.error_line(),
            "网络类失败先试：git config http.sslBackend openssl，然后 git fetch origin",
        )
    if failures:
        report.add(
            FAIL,
            "写回引用之后的命令有失败",
            "已在上方标出",
            "引用已写回，可重跑 python scripts/doctor.py --check 看剩余问题",
        )
    if failures or not fetch.ok:
        report.render()
        return 1
    report.ok("重量修复完成", f"已写回 {len(restored)} 个分支引用：{'、'.join(restored)}")
    report.ok("复查", "python scripts/doctor.py --check")
    report.render()
    return 0


# ---------------------------------------------------------------------------
# ③ --restore
# ---------------------------------------------------------------------------


def cmd_restore(args: argparse.Namespace) -> int:
    ctx = build_ctx(Path(args.repo))
    print_header("恢复工作区缺失的已跟踪文件（默认 dry-run）", ctx)
    report = Report()

    if ctx.git_dir is None:
        report.add(FAIL, "未找到 .git", f"从 {ctx.repo_arg} 向上都没找到", "用 --repo 指定仓库根")
        report.render()
        return 1

    missing, tracked_total = list_missing_tracked(ctx)
    if tracked_total < 0:
        report.add(
            FAIL,
            "无法列出已跟踪文件",
            "git ls-files 执行失败（git 可能整体不可用）",
            "先修 refs：python scripts/doctor.py --fix-refs",
        )
        report.render()
        return 1

    if not missing:
        report.ok("无需恢复", f"已跟踪 {tracked_total} 个文件，都在磁盘上")
        report.render()
        return 0

    print(f"磁盘上缺失的已跟踪文件（共 {len(missing)} 个）：")
    for path in missing:
        print(f"  - {path}")
    print(f"\n{BACKUP_REMINDER}")

    # 按批次构造命令，避免命令行长度超限
    batches = [missing[i : i + 100] for i in range(0, len(missing), 100)]
    print("\n将要执行的命令：")
    for batch in batches:
        head = " ".join(batch[:3])
        more = f" …（共 {len(batch)} 个）" if len(batch) > 3 else ""
        print(f"  $ git -C {shlex.quote(str(ctx.repo))} restore -- {head}{more}")

    if not args.yes:
        print("\n（dry-run：以上命令**均未执行**，磁盘没有任何改动。确认无误后加 --yes）")
        report.ok("dry-run 完成", f"待恢复 {len(missing)} 个文件，未修改任何东西")
        report.render()
        return 0

    print("\n开始执行：")
    failures = 0
    for batch in batches:
        result = git(ctx.repo, "restore", "--", *batch, timeout=GIT_SLOW_TIMEOUT)
        mark = OK if result.ok else FAIL
        print(f"  {mark} git restore -- （{len(batch)} 个文件）")
        if not result.ok:
            failures += 1
            print(f"      {result.error_line()}")
            break

    remaining, _ = list_missing_tracked(ctx)
    if failures:
        report.add(FAIL, "恢复命令执行失败", "已在上方标出", "把报错贴到 Issue，不要叠加重试")
        report.render()
        return 1
    if remaining:
        report.add(
            FAIL,
            f"仍有 {len(remaining)} 个文件缺失",
            "、".join(remaining[:10]),
            "这些文件可能不在 index 里：git status 看具体状态后再处理",
        )
        report.render()
        return 1
    report.ok("恢复完成", f"已恢复 {len(missing)} 个文件")
    report.ok("复查", "python scripts/doctor.py --check")
    report.render()
    return 0


# ---------------------------------------------------------------------------
# ④ --backup-git
# ---------------------------------------------------------------------------


def cmd_backup_git(args: argparse.Namespace) -> int:
    ctx = build_ctx(Path(args.repo))
    print_header("把 .git 备份到项目外", ctx)
    report = Report()

    if ctx.git_dir is None:
        report.add(FAIL, "未找到 .git", f"从 {ctx.repo_arg} 向上都没找到", "用 --repo 指定仓库根")
        report.render()
        return 1

    if args.dest:
        dest = Path(args.dest)
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = ctx.repo.parent / f"{ctx.repo.name}_git_backup_{stamp}"

    try:
        dest_abs = dest.resolve()
    except OSError:
        dest_abs = dest
    if dest_abs.is_relative_to(ctx.repo):
        report.add(
            FAIL,
            "备份目标在项目内（会被清理程序一起清掉）",
            f"目标：{dest_abs}",
            "换到项目外，例如 --dest D:/git_backups/xizhi-0918",
        )
        report.render()
        return 1
    if dest.exists():
        report.add(
            FAIL,
            "备份目标已存在，拒绝覆盖",
            f"目标：{dest}",
            "换一个 --dest（本脚本从不删除/覆盖已有目录）",
        )
        report.render()
        return 1

    source = ctx.git_dir
    print(f"源：{source}")
    print(f"目标：{dest}")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest, symlinks=False)
    except (OSError, shutil.Error) as exc:
        report.add(FAIL, "复制 .git 失败", str(exc), "确认目标盘可写、且没有占用中的 pack 文件")
        report.render()
        return 1

    src_files = count_files(source)
    dst_files = count_files(dest)
    src_size = dir_size(source)
    dst_size = dir_size(dest)
    report.ok("备份路径", str(dest.resolve()))
    report.ok("文件数校验", f"源 {src_files} 个 / 备份 {dst_files} 个")
    report.ok("体积校验", f"源 {human_size(src_size)} / 备份 {human_size(dst_size)}")
    if src_files != dst_files:
        report.add(
            FAIL,
            "文件数不一致，备份可能不完整",
            f"{src_files} → {dst_files}",
            "先别做任何 git 改动，重新备份一次",
        )
    report.render()
    return 0 if report.healthy else 1


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doctor.py",
        description=(
            "xizhi doctor —— .git 体检 + 安全恢复。"
            "默认（不加子命令）只做 --check：纯只读；"
            "--fix-refs / --restore 默认 dry-run，必须加 --yes 才真的改动。"
        ),
        epilog=(
            "示例：\n"
            "  python scripts/doctor.py                     # 体检（只读，默认动作）\n"
            "  python scripts/doctor.py --fix-refs          # 看要执行什么（dry-run）\n"
            "  python scripts/doctor.py --fix-refs --yes    # 真的修 refs\n"
            "  python scripts/doctor.py --restore           # 看缺失文件清单（dry-run）\n"
            "  python scripts/doctor.py --restore --yes     # 真的恢复\n"
            "  python scripts/doctor.py --backup-git        # 备份 .git 到项目外\n"
            "\n"
            "安全底线：--check 不改任何东西；--fix-refs / --restore 不加 --yes 时零副作用；\n"
            "本脚本永不执行 rebase / clean / reset --hard，也永不删除文件。\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", default=".", help="仓库路径（默认当前目录，会向上找 .git）")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="体检（默认动作，只读）")
    group.add_argument("--fix-refs", action="store_true", help="修 refs 类故障（默认 dry-run）")
    group.add_argument("--restore", action="store_true", help="恢复工作区缺失的已跟踪文件（默认 dry-run）")
    group.add_argument("--backup-git", action="store_true", help="把 .git 备份到项目外")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行 --fix-refs / --restore（不加就只打印，不动任何东西）",
    )
    parser.add_argument("--dest", default=None, help="--backup-git 的目标目录（默认项目外的带时间戳目录）")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    args = build_parser().parse_args(argv)
    if args.fix_refs:
        return cmd_fix_refs(args)
    if args.restore:
        return cmd_restore(args)
    if args.backup_git:
        return cmd_backup_git(args)
    return cmd_check(args)


if __name__ == "__main__":
    sys.exit(main())
