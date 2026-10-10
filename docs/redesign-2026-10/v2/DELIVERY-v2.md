# 析知 XiZhi 前端视觉改版 v2 交付说明 · Learning Atlas（2026-10-10）

> 依据：`kimi_k3_xizhi_redesign_prompt(2).md`（v2 提示词）+ `xizhi_k3_visual_reference`（六页效果图 + MOTION_AND_STYLE_NOTES）。
> 在 v1（`docs/redesign-2026-10/DELIVERY.md`）基础上整体替换为 **Learning Atlas** 视觉系统。
> 不变式不变：六个路由、API 契约、真实状态、业务流程、数据语义均未改动；SPEC v2.3 仍为冻结基线。

## 1. Art direction 决策（5 项）

一句话：**把复杂工作台设计成一本持续展开的「知识地图档案」——深夜蓝像制图台，暖纸档案承载阅读内容，电光蓝只做主要行动，荧光与珊瑚橙只做小面积路径/状态强调。**

| # | 决策 | 落点 |
|---|---|---|
| 1 | **主色/辅助色** | 主行动色电光蓝 `#315cff`（延续品牌蓝语义、微提明度）；深蓝 `#101c2e`（制图台）、暖纸 `#f2efe7/#fffdf7`（阅读面）；lime `#d9ed83`（深蓝底路径/选中强调）、teal `#62c8b4`（软前置）、coral `#ee704c`（待复核/序号），三者只作小面积强调 |
| 2 | **字体对比** | 系统中文栈 + Georgia 衬线斜体（仅用于 eyebrow 序号、里程碑数字、引文，营造编辑式档案感）；标题 34–48px 紧字距 700，正文 14，辅助 ≥12px |
| 3 | **背景材质** | 双材质：暖纸底 + 细颗粒点阵（CSS radial-gradient）；深蓝面 + 制图网格 + 柔光（linear-gradient mask）；非图片、零采购 |
| 4 | **图形语言** | 路径线（虚线沿路径流动）、节点光晕、轨道圆环、坐标网格、档案编号（eyebrow 01–06 + INDEX）；概览/图谱/路径的深蓝制图面是全站识别中心 |
| 5 | **动效节奏** | 切页 220ms 淡入上移；概览路径虚线 18s 流动；节点呼吸 3.6s；上传轨道 24s 旋转；图谱仅在选中节点时荧光描边+相邻边发光；学习路径逐项 80ms 出现；reduced-motion 全部瞬时 |

## 2. 与 v2 提示词新增要求的对应

| 提示词要求 | 落实 |
|---|---|
| 工程字段名中文化（`cycle_count` / `pruned_count` / `avg_quality_score` …） | 图谱统计条与质量报告全部改为中文概念名（依赖环数 / 已剪除的成环边 / 冲突边（结构-语义）/ 解析质量均分…），**不再出现任何原始字段名**（`buildMetrics.ts` 15 处 label 已改） |
| 首页固定数字 629 / 462 / 35 验证来源 | **已实测可验证，保留**：629 = `/knowledge-points` total；462 = 重复组成员总数 616 − 组数 154（同组副本口径）；35 = `kp_42b16cd4_000_000_012` 的 `duplicate_group_size`。文案标注「已实测」 |
| 390px 首页/图谱右侧裁切 | 本地六路由 390px 实测 `scrollWidth ≤ clientWidth` 全部通过（截图 `v2/*-390.png`），无整页横向溢出 |
| 图谱节点默认缩放下标签截断较多 | 节点卡改为「标题 + 难度说明行」两行布局；初始视图保持「可读优先」（<0.5 时 0.5 倍左对齐起点层） |
| 每页一个原创焦点 | 概览深蓝 hero（路径描绘）；素材蓝灰上传面×深蓝流程说明卡；图谱深蓝画布+暖纸证据面板；路径深蓝目标面板+INDEX 侧栏；答疑深蓝原则板+暖纸对话；报告深蓝总览+质量环+暖纸审计表 |
| 图谱硬/软前置至少两种视觉线索 | 线型（实线 vs 点线）+ 箭头形态（实心 vs 空心）+ 颜色（灰蓝 vs 青绿）三重线索；选中态荧光描边+发光 |
| 详情不被画布遮挡 | 桌面（≥lg）改为画布右侧**内嵌证据面板**（不再弹层）；手机保持底部抽屉 |

## 3. 改动文件清单（v2）

- 底座：`tailwind.config.js`（atlas 双材质 + electric/lime/teal/coral + serif）、`src/index.css`（纸颗粒、排版类、atlas-draw/breathe/spin、page-enter）
- 壳层：`App.tsx`（深蓝制图侧栏 + 面包屑顶栏 + 切页动画）
- 概览：`pages/Overview.tsx`（全量重写：hero/流程带/A-D 入口/原则板）
- 素材：`pages/Materials.tsx`、`components/materials/{UploadDropzone,MaterialTable,ExtractPanel}.tsx`
- 图谱：`pages/Graph.tsx`、`components/graph/{GraphCanvas,GraphStatsPanel,KnowledgePointAside,KnowledgePointDetail,KnowledgePointDrawer}.tsx`（Detail 为新提取的共享内容，Aside 为新组件）
- 路径：`pages/Path.tsx`、`components/path/{PathHero,TargetPicker,PathTimeline}.tsx`
- 答疑：`pages/Tutor.tsx`、`components/tutor/{TurnCard,StateMachinePanel}.tsx`
- 报告：`pages/Report.tsx`、`components/report/{ReportOverview,AuditSheet,buildMetrics}.tsx`
- 公共：`lib/format.ts`（新增 `formatChapterRef` 章节去重格式化）

**依赖变更：无。** 零新增 npm 依赖；图标沿用 lucide-react；字体沿用系统栈 + Georgia（系统自带）；
装饰图形全部为自制内联 SVG/CSS（概览/路径的路线图参考随附视觉包的内嵌 SVG，属任务输入材料，非第三方资产）。
**第三方代码/资产采用：零**（React Bits / Uiverse / Aceternity / Anime.js / MotionSites 一律未采用，未超出一个外部组件的上限）。

## 4. 走查结果（Edge headless + CDP，远端生产后端真数据）

| 检查项 | 结果 |
|---|---|
| 六路由 × 1440×900 / 1280×800 / 768×1024 / 390×844 | ✅ 全部渲染，截图在 `docs/redesign-2026-10/v2/` |
| 390px 整页横向滚动 | ✅ 六路由全部为 false |
| 控制台错误 / 未捕获异常 | ✅ 六路由均为 0 |
| 生产构建（tsc --noEmit + vite build） | ✅ 通过（`index-Bm4-Fca8.js` 403KB / `index-DKjmNMju.css` 57.5KB） |
| 图谱节点点击 → 桌面内嵌证据面板出现详情；荧光选中态+相邻边发光 | ✅ 实测 |
| 手机图谱：筛选折叠、点节点出底部抽屉 | ✅ 实测 |
| Tab 焦点环（2px `#315cff`，可信键事件） | ✅ 导航六项逐一可见 |
| `prefers-reduced-motion: reduce` | ✅ 动画时长塌缩为 0.01ms（仿真实测） |
| 移动抽屉导航（遮罩/Escape/焦点返回） | ✅ v1 已验，结构未变 |

**未验证项（如实声明）**：① 后端失败/断网各状态的视觉未逐一触发（逻辑未改）；② SSE 流式答疑长会话未重跑；
③ 真实上传未执行（避免改动远端数据）；④ 概览 hero 路径描绘动画的逐帧观感需真机肉眼复核（合成帧已验证无错误）。

## 5. 已知限制

- 图谱 200 节点全部「待复核」是真实数据状态（复核队列 200），因此画布以珊瑚虚线为主——这是数据真相，不是配色问题。
- 章节字段存在噪声数据（如 `number=title='299'`），已用 `formatChapterRef` 去重并加「CH.」前缀；源头修复在后端（P1/P2 域）。
- 答疑页「回答所依据的材料」展示最近一轮 retrieved 事件的知识点（至多 6 个），原文块不逐一列出（列表在溯源卡内）。
