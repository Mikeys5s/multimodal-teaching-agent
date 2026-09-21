# Git 协作规范

## 1. 首次获取项目

仓库成员接受 GitHub 邀请后，运行：

```bash
git clone <仓库地址>
cd multimodal-teaching-agent
```

首次使用 Git 时设置自己的提交身份：

```bash
git config --global user.name "你的名字"
git config --global user.email "你的 GitHub 邮箱"
```

## 2. 日常开发流程

不要直接在 `main` 分支开发。每一项任务使用一个短分支：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/简短任务名
```

完成一小段可说明的工作后提交：

```bash
git status
git add <本次相关文件>
git commit -m "feat: 简要说明完成了什么"
git push -u origin feat/简短任务名
```

随后在 GitHub 创建 Pull Request（PR），由至少一名队友检查后合并。合并完成后清理本地分支：

```bash
git switch main
git pull --ff-only origin main
git branch -d feat/简短任务名
```

## 3. 分支命名

- `feat/...`：新功能
- `fix/...`：修复问题
- `docs/...`：文档
- `test/...`：测试
- `chore/...`：工程配置、依赖或杂项

示例：`feat/material-parser`、`fix/upload-timeout`、`docs/demo-guide`。

## 4. 提交信息

推荐使用“类型 + 简短说明”：

```text
feat: 支持 PDF 素材上传
fix: 修复图片解析超时
docs: 补充本地启动步骤
test: 增加知识点抽取测试
chore: 更新依赖版本
```

一次提交只解决一个主题。不要使用“改一下”“最终版”“update”等无法追溯的说明。

## 5. 冲突处理

推送前先同步 `main`：

```bash
git fetch origin
git rebase origin/main
```

若出现冲突，打开冲突文件，保留正确内容并删除冲突标记，然后运行：

```bash
git add <已解决的文件>
git rebase --continue
```

确认无误后推送。已经推送过且经过 rebase 的个人功能分支，使用：

```bash
git push --force-with-lease
```

不要对 `main` 强制推送，也不要使用 `git push --force`。

## 6. 文件与安全规则

- 禁止提交 `.env`、API Key、密码、Token、私钥或真实用户隐私数据。
- 配置示例使用 `.env.example`，其中只写变量名和无敏感性的示例值。
- 提交前务必运行 `git status` 和 `git diff --staged`。
- 模型权重、原始数据集、视频和大型演示文件应使用 Git LFS 或团队约定的对象存储。
- 需求讨论和任务分工写在 GitHub Issues；代码审查和合并结论写在 PR，避免只留在聊天记录中。

## 7. 提交前跑测试

**一条命令，不依赖任何环境记忆：**

```bash
bash scripts/test.sh           # 跑全部
bash scripts/test.sh tutor     # 只跑文件名含 tutor 的
bash scripts/test.sh --cov     # 带覆盖率
```

脚本会**先做依赖自检**：缺什么直接说、并打印装法。
（缺 `python-pptx` 时**必须用官方源** `https://pypi.org/simple` —— 清华源上找不到。）

### 为什么单独立这一节

2026-09-21 发现「测试跑不起来」有**两个同时存在的原因**：

| 位置 | 缺什么 |
|---|---|
| 本机 `.venv` | `python-pptx` / `numpy` / `pypdf`（被清理工具删过） |
| **生产容器** | **没有 pytest、也没有 `tests/`**（不在 `Dockerfile` 的 COPY 里） |

**结果是每个人都在"两边都不行"的夹缝里凑合验证** ——
有人跑一半、有人跳过、有人临时补依赖跑完但**别人复现不出来**。

**所以：跑测试的方式必须固化成一个文件，而不是各自记忆。**

### ⚠️ 两条纪律

1. **别只跑一部分。** 同一天里，`tests/test_tutor_state.py` 全绿的同时，
   `tests/test_api_smoke.py` 有 **5 个**失败 —— 而它们绿了很久，
   **因为它们一直跟着一个错误的实现走**（断言里写死了 `create_session` 返回的常量）。
   **只跑一部分测试，等于没跑。**

2. **`--strict` 类判据要分清「不达标」和「没数据可判」。**
   `r.passed` 有三种值：`True` / `False` / **`None`（样本为 0）**。
   写 `if not r.passed` 会把 `None` 算成失败 ——
   **一个健康的图也会非零退出**，CI 会把"库里没数据"误报成"质量不合格"。
   **判据写 `is False`。**

## 8. 紧急撤销

撤销尚未暂存的单个文件修改：

```bash
git restore <文件>
```

取消暂存但保留文件修改：

```bash
git restore --staged <文件>
```

撤销已经共享的提交，请创建反向提交，不要改写公共历史：

```bash
git revert <提交哈希>
```
