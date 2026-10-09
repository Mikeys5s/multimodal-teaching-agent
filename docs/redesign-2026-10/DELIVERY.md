# 析知 XiZhi 前端视觉改版交付说明（2026-10-09）

> 范围：在不改变路由、业务流程、API 契约与数据语义的前提下，完成前端视觉改版与响应式重建。
> 基线：SPEC v2.3（已冻结）。本次未修改任何产品规则、状态枚举、接口字段与业务文案语义。

## 1. 设计方向

**「学习地图 Atlas」**：把 XiZhi 定位成"知识的测绘工具"——知识图谱的节点是"地标"，依赖边是"路线"，
学习路径是"里程碑行程单"。一句话逻辑：教育 AI 工作台的核心资产是"结构化的知识关系"，
视觉系统让这种关系成为第一眼就能辨认的产品记忆点，而不是又一套卡片网格后台。

落地方式：
- 图谱节点改为「地标卡」：白底 + 左侧难度色轨 + 难度数字徽章；待复核 = 琥珀虚线描边 + `!` 角标。
- 硬/软前置用**三重线索**区分：线型（实线 vs 点线）、箭头形态（实心 vs 空心）、颜色深浅；
  选中节点时关联边变品牌蓝加粗、非关联边压淡。图例同步更新。
- 学习路径为里程碑时间线：序号圆牌 + 连接线，最后一步即目标（品牌蓝描边 + 「目标」徽标），
  步骤逐项淡入（减少动效时瞬时呈现）。
- 其余页面克制处理：纸白画布、1px 分隔线代替层层卡片阴影、单主行动色（品牌蓝）。

## 2. 设计 token（已落实到 tailwind.config.js 与 index.css）

| Token | 值 | 用途 |
|---|---|---|
| canvas | `#F8FAFC`（slate-50） | 页面底色 |
| surface / surface-muted | `#FFFFFF` / `#F1F5F9` | 内容面 / 次级分区 |
| border | `#E2E8F0`（slate-200） | 分隔线与控件边框 |
| text-primary / secondary / muted | `#0F172A` / `#334155` / `#64748B` | 文字三级 |
| brand / hover / soft | `#2563EB` / `#1D4ED8` / `#EFF6FF` | 唯一主行动色（品牌延续） |
| success / warning / danger / info | `#166534` / `#92400E` / `#991B1B` / `#1E40AF`（各配 soft/line） | 仅状态语义，必配文字或图标 |
| difficulty 1–5 | `#059669 #65A30D #D97706 #EA580C #DC2626` | 节点色轨与难度徽章 |
| focus | `#2563EB`，2px 环 + 2px 偏移 | 全局 `:focus-visible` |

**关键调整记录**（相对建议基准，均有对比度依据）：
1. **难度色阶整体加深一档**（如 `#84cc16`→`#65a30d`）：原值在 12px 文字/描边场景对白底不足 4.5:1。
   色相族不变，SPEC「节点颜色映射难度」的语义不变。
2. **状态徽章文字色加深**（如 parsing `#3b82f6`→`#1d4ed8`、failed `#ef4444`→`#991b1b`）：12px 徽章文字达 4.5:1。
3. 新增语义色对 `success/warning/danger/info`（文字 + 浅底 + 边线三件套），全站替换散落的
   amber/red/emerald/rose/orange 临时类，状态颜色语义（红=失败/危险、黄=警告/待复核、绿=成功）未变。
4. 新增 `shadow-overlay`（弹层）、`duration-120/160/220`（动效阶梯）、`text-2xs`（12px/500 标签）。

排版阶梯：页面标题 22–24/600、区块标题 16–18/600、正文 14/22、辅助 13/20、标签 12/18（500）、
关键数字 28–36/600 tabular-nums。必要信息不低于 12px（原 `text-[11px]/[10px]` 已全部清除）。
间距按 4/8/12/16/24/32/48 阶梯；圆角三档：控件 8 / 卡片与节点 12 / 弹层 16。

## 3. 响应式结构

- **移除** `#root { min-width: 1024px }`（index.css），主内容全程 `min-w-0`。
- 桌面（≥lg）：240px 常驻侧栏 + 56px 顶栏 + 内容区。
- 平板（md）：顶栏汉堡菜单 + 抽屉导航；筛选/表单全宽堆叠；素材清单用堆叠列表（避免容器内横滚找操作列）。
- 手机（<md）：左抽屉导航（w-72 ≤320px、遮罩、body 滚动锁定、Escape 关闭、关闭后焦点回菜单按钮）；
  不做六项底部导航。主要触控目标 ≥44px（按钮、导航项、图标按钮、画布缩放控件、示例问题 chip）。
- 弹层：知识点详情/复核队列/素材预览统一「桌面右侧抽屉 / 手机底部抽屉（或全屏）」，
  焦点进入、Escape 关闭、关闭后焦点返回、背景滚动锁定。
- 表格：桌面表格容器内可横滚（首要识别字段文件名+时间首列可见）；手机/平板为字段堆叠列表。
- 图谱：画布在自己的容器内平移/缩放；**初始视图改为「可读优先」**——全景缩放 <0.5 时按 0.5 倍左对齐
  到先修起点层（原先 200 节点缩到 10% 成一条色带，无法阅读）；「适应画布」按钮保留全景。

## 4. 组件清单（路由｜组件｜数据来源｜状态｜处理）

图例：✅ 已改版并走查；➖ 语义未动仅 token 对齐。

| 路由 | 组件 | 数据来源 | 覆盖状态 | 处理 |
|---|---|---|---|---|
| 全局 | 侧栏导航（6 路由）+ SPEC 提示 | 静态 NAV_ITEMS | active/hover/焦点 | ✅ 桌面常驻+移动抽屉，文案/路由/active 规则不变 |
| 全局 | 顶栏 + BackendStatus | GET /health（30s 轮询） | 在线/离线/检测中 | ✅ 状态文字+圆点，小屏截不断 |
| 全局 | Button/Badge/Feedback（Loading/Empty/Error/Inline/ProgressBar/IndeterminateBar） | — | default/hover/focus/pressed/disabled/loading | ✅ 统一 40/44px、焦点环、语义色、文字+图标 |
| `/` | Hero + 主 CTA、QUICK_TOURS ×4、STAGES ×3、产品原则 | 静态 | — | ✅ 路线图母题（aria-hidden 纯装饰）、网格响应式 |
| `/materials` | UploadDropzone | GET /meta/capabilities | 默认/拖拽中/上传中/禁用 | ✅ 手机全宽点选入口，行为不变 |
| `/materials` | MaterialTable + UncertainNotes | GET /materials | 行内状态/存疑展开/忙碌禁用 | ✅ 桌面表格（1280 十列全见）+ 移动堆叠列表 |
| `/materials` | JobProgressPanel | GET /jobs/{id} 轮询 | 运行/完成/失败/部分完成 | ✅ token 对齐，stage_detail 原样展示不变 |
| `/materials` | ExtractPanel | POST /extract/knowledge | 空/不可抽取/提交错误(JOB_IN_PROGRESS)/部分成功 | ✅ token 对齐，「默认不勾选覆盖」语义不变 |
| `/materials` | MaterialPreviewDrawer + QuestionsPanel | GET /materials/{id}/blocks、/questions | 加载/错误/空/低置信标注/答案三态 | ✅ 弹层行为契约补齐（Escape/焦点/滚动锁） |
| `/graph` | 筛选栏（章节/上限/只看待复核/清空） | GET /knowledge-points、/knowledge-graph | 筛选启用标记 | ✅ 手机折叠为可展开面板 |
| `/graph` | 人工校验入口 | GET /review/queue | 待裁决数徽标 | ✅ 保留，徽标语义不变 |
| `/graph` | GraphStatsPanel | graph.stats | 环数/剪枝/冲突/规模 | ✅ 压缩为指标条，画布成核心区域 |
| `/graph` | GraphCanvas | 上述计算布局 | 平移/缩放/适应/选中/hover/键盘/空筛选 | ✅ 地标卡节点、三重线索边、可读初始视图、图例更新 |
| `/graph` | KnowledgePointDrawer | GET /knowledge-points/{id} | 加载/错误/待复核/重复组提示 | ✅ 桌面 360px 抽屉 / 手机底部抽屉 |
| `/graph` | ReviewDrawer | GET /review/queue、POST /review/decide | 空队列/裁决中/已采纳/已驳回留痕 | ✅ 驳回改 danger（高影响动作），软删除语义不变 |
| `/path` | TargetPicker | GET /knowledge-points | 筛选/空/错误/选中 | ✅ 表单手机全宽、触控 44px |
| `/path` | PathTimeline | GET /learning-path | 空/加载/错误/起点/目标 | ✅ 里程碑时间线、逐项淡入、目标徽标 |
| `/path` | GapAnalysisPanel | GET .../gap-analysis | 无硬前置警示/断层/建议/证据增删 | ✅ token 对齐 |
| `/tutor` | 会话条 + 示例问题 + 输入区 | POST /qa/sessions | 未创建/忙碌/删除确认 | ✅ 提问/中断主操作 44px |
| `/tutor` | TurnCard/TraceCard/StateBadge/DiagnosisPanel | SSE retrieved/state/delta/diagnosis/done | 流式/中断/不完整/拒答/协议告警 | ✅ token 对齐，事件顺序与结构不变 |
| `/tutor` | StateMachinePanel/ReportPanel | GET .../state、.../report | 未启用/加载/错误/阶梯进度 | ✅ 配色换为对比度达标的语义色 |
| `/report` | ReportOverview + MetricSection ×4 + MetricCard | GET /report/quality | pass/fail/info/missing（暂缺不显示 0） | ✅ 未达标标红+文字，网格响应式 |
| `/report` | HealthSelfCheck、ExportPanel | GET /health、/health/pragma、/export/... | 自检通过/异常、导出成功/失败 | ✅ token 对齐 |

未发现仓库中存在但未列入上表的可见组件；未新增任何产品功能或虚构状态。

## 5. 改动文件清单

- 样式与配置：`tailwind.config.js`、`src/index.css`
- 壳层：`src/App.tsx`（响应式抽屉导航、品牌徽标）
- UI 原语：`components/ui/{Button,Badge,Feedback}.tsx`、`components/layout/BackendStatus.tsx`
- 页面：`pages/{Overview,Materials,Graph,Path,Tutor,Report}.tsx`
- 组件：`components/materials/*`（6）、`components/graph/*`（4）、`components/path/*`（3）、
  `components/tutor/*`（7）、`components/report/*`（4）
- 数据层（仅色值）：`src/lib/format.ts`（DIFFICULTY_COLOR 加深一档，色相族不变）

**依赖变更：无。** 未新增/升级/移除任何 npm 依赖；未引入外部组件库、图标库、字体或动画引擎
（图标沿用 lucide-react，字体沿用系统回退链，动效为纯 CSS + 既有 SVG）。
**第三方代码/资产采用情况：无。** React Bits / Uiverse / Aceternity / Anime.js / MotionSites
仅作节奏参考，未复制任何代码或素材；全任务零采购，无许可风险项需要声明。

## 6. 动效说明

- 导航/按钮颜色反馈 120ms；内容显现 160ms（`.xizhi-rise`，学习路径逐项 60ms 阶梯）；
  抽屉/弹层 220ms。骨架/加载沿用 `animate-pulse`。
- 图谱仅在选中/hover 节点时强调相邻边（无持续动画）；上传与任务进度只跟随真实后端状态
  （不定进度条 `IndeterminateBar` 不伪造百分比）。
- `prefers-reduced-motion: reduce`：base 层将所有动画/过渡压到 0.01ms（已实测 emulation 生效）。

## 7. 走查结果（真实浏览器，Edge headless + CDP，远端后端真实数据）

| 检查项 | 结果 |
|---|---|
| 六路由 1440×900 / 1280×800 / 768×1024 / 390×844 渲染 | ✅ 截图见 `docs/redesign-2026-10/` |
| 390px 整页横向滚动 | ✅ 无（`document.scrollWidth <= clientWidth` 六路由全过） |
| 控制台错误 / 未捕获异常 | ✅ 六路由均为 0 |
| 生产构建（tsc --noEmit + vite build） | ✅ 通过（1620 模块；仅 1 条 api.ts 动态导入 chunk 警告，为既有现象） |
| 移动抽屉导航：打开/6 项可达/Escape 关闭/焦点回菜单按钮 | ✅ 实测通过 |
| 图谱节点点击→详情抽屉（真实 KP 数据）→Escape 关闭 | ✅ 实测通过 |
| 手机图谱：筛选折叠展开、节点详情底部抽屉 | ✅ 实测通过 |
| 键盘 Tab 焦点环（2px 品牌蓝，可信键事件实测） | ✅ 导航六项逐一可见 |
| reduced-motion 仿真 | ✅ 动画时长塌缩为 0.01ms |
| 空/加载/失败/部分完成/成功状态 | ✅ 代码路径全部保留（未逐一触发后端失败态；失败文案来自后端原样展示的逻辑未动） |

**未验证项（如实声明）**：① 后端失败/断网各状态的视觉表现未逐一触发（逻辑未改，沿用原组件）；
② SSE 流式答疑长会话未重新跑一轮（本轮未调用 LLM 问答，流式渲染代码未改动）；
③ 上传真实文件流程未执行（避免改动远端数据），上传区为静态渲染检查。

## 8. 已知限制

- 图谱在 400 节点上限下的全景仍会很密（数据本质）；初始视图按可读缩放左对齐是刻意的取舍。
- 节点难度数字徽章为白字压难度色（11px 图形文字），对比度约 3.3:1——难度同时以色轨、
  徽章、aria-label 与详情页文字呈现，不单独依赖该数字可读性。
- 素材表在 1024–1279px 区间为容器内横滚（首要识别列保持可见），1280+ 十列全显。
