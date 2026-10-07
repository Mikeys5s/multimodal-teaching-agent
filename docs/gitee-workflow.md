# Gitee 协作流程（2026-10-07 起生效）

> 项目已从 GitHub 迁至 Gitee。**以后所有 PR、Issue、代码审查都在 Gitee 上进行。**
> GitHub 仓库保留为**只读历史镜像**，不再接收新的推送与 PR。

## 1. 仓库地址

| 用途 | 远程名 | 地址 |
|---|---|---|
| **主仓库（读写）** | `origin` | <https://gitee.com/mikey_code/multimodal-teaching-agent> |
| 历史镜像（只读） | `github` | <https://github.com/RyeYen/multimodal-teaching-agent> |

```bash
git remote -v
# origin    https://gitee.com/mikey_code/multimodal-teaching-agent.git (fetch/push)
# github    https://github.com/RyeYen/multimodal-teaching-agent.git      (fetch/push)
```

**约定**：不带远程名的 `git push` / `git pull` 一律走 `origin`（Gitee）。
不要再往 `github` 推 —— 两个仓库的 `main` 已经分叉，互相推会造成历史打架。

## 2. 首次配置（每台机器一次）

### 2.1 提交身份

```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"
```

### 2.2 Gitee 凭据

Gitee 的 HTTPS 推送需要**私人令牌（PAT）**，不能用账号密码。

1. 打开 <https://gitee.com/profile/personal_access_tokens> → 新建令牌
   - 名称：`multimodal-teaching-agent`
   - 权限：至少勾选 **`projects`**（仓库读写）
2. 复制令牌（**只显示一次**），然后二选一：

**方式 A：交给 Windows 凭据管理器（推荐，令牌加密存储，不进任何仓库文件）**

```bash
git config --global credential.https://gitee.com.username <你的Gitee用户名>
printf 'protocol=https\nhost=gitee.com\nusername=<你的Gitee用户名>\npassword=<粘贴令牌>\n\n' | git credential approve
```

验证（不推送任何内容，只读）：

```bash
git ls-remote origin > /dev/null && echo OK
```

**方式 B：独立凭据文件（GCM 不识别 gitee 时的备用方案）**

```bash
git config --global credential.https://gitee.com.helper "store --file=C:/Users/<你>/.git-credentials-gitee"
printf 'https://<用户名>:<令牌>@gitee.com\n' >> ~/.git-credentials-gitee
```

> ⚠️ 方式 B 是**明文**文件，务必放在仓库之外，且**绝对不要**提交进版本库。

**方式 C：SSH**

```bash
ssh-keygen -t ed25519 -C "你的邮箱"
# 把 ~/.ssh/id_ed25519.pub 内容贴到 https://gitee.com/profile/sshkeys
git remote set-url origin git@gitee.com:mikey_code/multimodal-teaching-agent.git
```

## 3. 日常开发流程

```bash
# 1) 同步 main（只快进，不产生合并提交）
git switch main
git pull --ff-only origin main

# 2) 开短分支
git switch -c feat/简短任务名

# 3) 改代码、跑测试
bash scripts/test.sh

# 4) 提交并推送
git add <本次相关文件>
git commit -m "feat: 简要说明完成了什么"
git push -u origin feat/简短任务名
```

**5) 开 PR**：推送后终端会打印一条 Gitee 给出的创建链接；也可以直接打开
<https://gitee.com/mikey_code/multimodal-teaching-agent/pulls> 点「新建 Pull Request」，
选择你的分支 → `main`，填写说明后提交。

6) 至少一名队友审查通过后合并（推荐用 **squash** 或 **merge**，不用 rebase）。
合并完成后清理：

```bash
git switch main
git pull --ff-only origin main
git branch -d feat/简短任务名
```

## 4. ⚠️ 本机硬约束：不要用 `git rebase`

`CONTRIBUTING.md` §5 原先建议用 `git rebase origin/main`，**在本机这台机器上必须改成 merge**。

原因：本机实测 **`git rebase` 会清掉 `.git/refs/`**，之后仓库直接变成
`fatal: not a git repository`，严重时 `objects` 也会掉文件（已复现多次）。

**替代做法**（任选其一）：

```bash
# 方案 1：merge（安全，会多一个合并提交）
git fetch origin
git merge origin/main

# 方案 2：不动本仓库 —— 另开一份新克隆，在新克隆里把分支建在最新 main 上
git clone --no-checkout https://gitee.com/mikey_code/multimodal-teaching-agent.git ../mta-new
cd ../mta-new && git switch -c feat/任务名 origin/main
```

同理，本机还有两个已知坑：

- **`git switch` / `checkout` 切到「文件更少」的分支会删掉工作区文件**（safe-delete 拦下 git 的删除，命令失败但文件已丢，还留下 `.git/index.lock`）。
  降低频率：**一个克隆 = 一条支线**。
- **`git merge` 前先确认目标方向没有删除条目**：

  ```bash
  git diff --name-status HEAD..origin/main | grep -c '^D'   # 期望 0
  ```

动 `.git` 之前先备份：

```bash
python -c "import shutil;shutil.copytree(r'.git', r'../mta-git-backup')"
```

## 5. 分支命名与提交信息

沿用 `CONTRIBUTING.md`：
分支前缀 `feat/` `fix/` `docs/` `test/` `chore/`；
提交信息「类型 + 简短说明」（`feat: 支持 PDF 素材上传`）。

一次提交只解决一个主题。禁止 `改一下` / `最终版` / `update`。

## 6. 迁移遗留待办

以下文件仍写着 GitHub 的地址，需在后续 PR 中一并更新：

| 文件 | 位置 | 现状 |
|---|---|---|
| `CONTRIBUTING.md` | §1 / §2 / §6 | 写「接受 GitHub 邀请」「在 GitHub 创建 Pull Request」「写在 GitHub Issues」 |
| `scripts/review-verify.sh` | 第 57、118 行 | `REPO_SLUG="RyeYen/multimodal-teaching-agent"`，从 `github.com` 克隆 |
| `docs/deployment.md` | 第 92 行 | `git clone https://github.com/RyeYen/...` |
| `docs/delivery-checklist.md` | 第 121 行 | 用 `api.github.com` 判仓库是否公开 |
| `README.md` | 第 73–75 行 | 贡献者个人主页链接（GitHub 主页，属身份信息，可保留） |
| `SPEC.md` / `docs/tasks/*` / `docs/buddy-logs/*` | — | **历史记录，不改**（改了就失去可溯源价值） |

## 7. 本机环境现状（2026-10-07 迁移后）

- 本地仓库 `D:\multimodal-teaching-agent`：`main` = `origin/main` = Gitee `main`（快进完成，工作区干净）
- `.git` 备份：`D:\multimodal-teaching-agent-git-backup-20261007-195646`
- 迁移时挪走的 5 个未跟踪文件（原 `docs/demo-script.md` 9/21 旧版等）：
  `D:\multimodal-teaching-agent\.learnbuddy\_parked_untracked_20261007-195646\`
- 8 个已废弃的本地分支（`chore/review-followups`、`docs/p1-env-readiness`、`feat/material-parser`、
  `feat/parse-denoise`、`feat/pptx-parse`、`fix/two-column-reading-order`、
  `test/parse-coverage-hardening`、`tmp-base-verify`）：其内容均已包含在 Gitee `main` 中，
  upstream 显示 `[gone]`，可安全删除，也可暂时留作历史参考。
