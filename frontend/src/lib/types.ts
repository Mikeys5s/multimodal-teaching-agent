/**
 * 全局类型定义 —— 严格对齐 docs/api-spec.md **v1.3**（2026-09-17 冻结，共 28 个端点）。
 * 任何字段改动都必须先改 api-spec，再改这里（SPEC §9.2 接口冻结纪律：
 * 允许「新增端点 / 新增可选字段」，不允许改已有字段名或类型）。
 *
 * v1.3 相对 v1.2 的 6 处变更中，对本文件有影响的是：
 *   ① 新增 `GET /api/health/pragma`（端点数 27 → 28）→ 见 `PragmaOut`
 *   ② 非 JSON 响应（markdown / CSV）的请求标识走 `X-Request-ID` **响应头**
 *      → 见 `REQUEST_ID_HEADER`，实现见 `api.ts` 的 `requestText()`
 *   ③ SSE 事件补 `id:` 字段（与 `data.seq` 一致、会话内单调递增）
 *      → 5 个 SSE 负载类型均新增必填 `seq`
 *   ④ `gap-analysis` 的 `student_evidence` 为**可重复**查询参数 → 见 `GapAnalysisQuery`
 *   ⑤ `needs_review` 查询参数统一为布尔 `true` / `false`（传 `1`/`0` → 400）
 *   ⑥ 分页补默认值与越界行为 → 见 `PageQuery`
 */

/* ------------------------------------------------------------------ *
 * 1. 通用约定（api-spec §1）
 * ------------------------------------------------------------------ */

export type ApiErrorCode =
  | 'INVALID_PARAM'
  | 'UNSUPPORTED_FORMAT'
  | 'FILE_TOO_LARGE'
  | 'NOT_FOUND'
  | 'JOB_IN_PROGRESS'
  | 'LLM_SCHEMA_INVALID'
  | 'INTERNAL'
  | 'LLM_UNAVAILABLE'
  /** 前端本地错误码：网络失败 / 非 JSON 响应，不属于后端错误码表 */
  | 'NETWORK_ERROR'
  | 'BAD_RESPONSE'

export interface ApiErrorBody {
  code: ApiErrorCode
  message: string
  detail?: unknown
}

export interface ApiOk<T> {
  ok: true
  data: T
  request_id: string
}

export interface ApiFail {
  ok: false
  error: ApiErrorBody
  request_id: string
}

export type ApiEnvelope<T> = ApiOk<T> | ApiFail

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/* ------------------------------------------------------------------ *
 * 1.1 非 JSON 响应的例外条款（api-spec §1.1，v1.3 明确）
 * ------------------------------------------------------------------ */

/**
 * 非 JSON 响应的请求标识**不在 body 里，而在响应头**。
 * 涉及：`GET /api/materials/{id}/markdown`（text/markdown）、
 *        `GET /api/export/knowledge-points?format=csv`（text/csv）。
 *
 * 约定（v1.3）：成功 → 原始内容 + `X-Request-ID` 响应头；
 *              **失败 → 仍返回 JSON 包封**（Content-Type 切回 application/json）。
 * 所以下载类请求要**先看 `Content-Type` 再决定解析分支**，不要只看 HTTP 状态码。
 */
export const REQUEST_ID_HEADER = 'X-Request-ID'

/** 非 JSON 响应的两种 Content-Type */
export type NonJsonContentType = 'text/markdown' | 'text/csv'

/* ------------------------------------------------------------------ *
 * 1.3 分页（api-spec §1.3）
 * ------------------------------------------------------------------ */

/**
 * 默认值由规格写死（v1.3 补充）：`page` 默认 **1**、`page_size` 默认 **20**、上限 **100**。
 * 越界（非整数 / 超出 1–100）后端返回 `400 INVALID_PARAM` —— 分页控件按这个写，不要自己猜。
 */
export interface PageQuery {
  page?: number
  page_size?: number
}

/* ------------------------------------------------------------------ *
 * 2. 健康检查与元信息（api-spec §2）
 * ------------------------------------------------------------------ */

export interface Health {
  status: string
  db: string
  llm: string
  version: string
}

/**
 * `GET /api/health/pragma`（v1.3 补登记，第 28 个端点）—— 读回当前连接的
 * **实际** SQLite pragma 值，供演示前的自检页使用。
 *
 * ★ `pragmas.foreign_keys` 必须为 `"1"`：这是「外键约束到底生效了没」的
 * 可验证答案，而不是靠读代码猜。
 */
export interface PragmaOut {
  pragmas: Record<string, string>
  db_file: string
}

/** 上传白名单项；前端据此渲染上传提示，不硬编码（api-spec §2） */
export interface MaterialTypeCap {
  ext: string[]
  label: string
  source_type: SourceType
  parse_method: ParseMethod
}

export interface Capabilities {
  material_types: MaterialTypeCap[]
  max_upload_mb: number
  max_page_count: number
  llm_provider: string
  llm_model: string
  /** 音频等不支持的格式必须能被前端明确拒绝（SPEC §5.1 边界与异常） */
  unsupported_ext: string[]
}

/* ------------------------------------------------------------------ *
 * 3. 素材（Stage 1，api-spec §3）
 * ------------------------------------------------------------------ */

export type SourceType = 'pdf_text' | 'pdf_scan' | 'docx' | 'pptx' | 'image'
export type ParseMethod = 'text_extract' | 'multimodal_llm' | 'ocr' | 'asr'
export type MaterialStatus = 'pending' | 'parsing' | 'done' | 'failed' | 'partial'

export type UncertainKind = 'ocr_low_confidence' | 'missing_field' | 'structure_unclear'
export type Severity = 'low' | 'medium' | 'high'

export interface UncertainNote {
  kind: UncertainKind
  page: number
  message: string
  severity: Severity
}

export interface Material {
  id: string
  filename: string
  mime_type: string
  size_bytes: number
  source_type: SourceType
  parse_method: ParseMethod
  status: MaterialStatus
  page_count: number
  duration_sec: number | null
  char_count: number
  quality_score: number
  uncertain_count: number
  uncertain_notes: UncertainNote[]
  created_at: string
}

export interface MaterialQuery extends PageQuery {
  status?: MaterialStatus
}

export interface UploadAccepted {
  material_id: string
  filename: string
  job_id: string
}

export interface UploadRejected {
  filename: string
  reason: string
}

/** POST /api/materials 的 data（部分失败仍返回 202，见 api-spec §3.1） */
export interface UploadResult {
  accepted: UploadAccepted[]
  rejected: UploadRejected[]
}

export interface Block {
  id: string
  seq: number
  page_no: number
  line_start: number
  line_end: number
  block_type: string
  heading_level: number | null
  content_md: string
  image_path: string | null
  ocr_confidence: number | null
}

export interface OutlineSection {
  number: string
  title: string
  section_id?: string
}

export interface OutlineChapter {
  number: string
  title: string
  chapter_id?: string
  sections: OutlineSection[]
}

export interface Outline {
  material_id: string
  chapters: OutlineChapter[]
}

export type QuestionType = 'single_choice' | 'multi_choice' | 'fill_blank' | 'short_answer'

/**
 * 从素材抽出的**原始**题目（`GET /api/materials/{id}/questions`）。
 * 与 `Example`（kp_examples）的区别：可能尚未归属到知识点，且**可能没有答案**。
 */
export interface Question {
  id: string
  material_id: string
  source_page: number | null
  source_block_id: string | null
  question_type: QuestionType
  stem_md: string
  /**
   * 选项数组的 **JSON 字符串** —— 后端字段名就是这个（`QuestionOut.options_json: str`），
   * 不是数组。前端取值要 `JSON.parse(options_json)`，不要当数组直接用。
   */
  options_json: string | null
  /** 材料未给答案时为 null */
  answer_md: string | null
  /**
   * ★ 材料里就没有答案 —— 与 Stage 1 的「存疑处」一一对应（v1.3 显式登记）。
   * 这是「宁缺毋错」原则的对外体现：展示时**要让它看起来像「材料里没给」**，
   * 而不是像「数据缺了一块」。
   */
  answer_missing: boolean
  extraction_confidence: number | null
  /** 归属知识点，Stage 2 回填 */
  pk_kp_id: string | null
}

/* ------------------------------------------------------------------ *
 * 4. 知识点与图谱（Stage 2，api-spec §4）
 * ------------------------------------------------------------------ */

export type Difficulty = 1 | 2 | 3 | 4 | 5
export type KpType = 'concept' | 'method' | 'skill' | 'principle' | 'protocol' | 'other'
export type RelationType = 'hard' | 'soft'

export interface ChapterRef {
  id: string
  number: string
  title: string
}

export interface SectionRef {
  id: string
  number: string
  title: string
}

export interface SourceRef {
  material_id: string
  material_name: string
  page: number
  block_id: string
  quote: string
}

export interface KnowledgePoint {
  id: string
  name: string
  summary_md: string
  difficulty: Difficulty
  difficulty_reason: string
  kp_type: KpType
  chapter: ChapterRef
  section: SectionRef
  source: SourceRef
  prerequisite_count: number
  example_count: number
  misconception_count: number
  needs_review: boolean
  confidence: number
}

export interface KnowledgePointQuery extends PageQuery {
  chapter_id?: string
  section_id?: string
  material_id?: string
  difficulty_min?: Difficulty
  difficulty_max?: Difficulty
  kp_type?: KpType
  /**
   * v1.3 统一为**严格布尔**：只能传 `true` / `false`。
   * ⚠️ 传 `1` / `0` 返回 `400 INVALID_PARAM`（规格明确「不静默兼容」）。
   * 不传 = 不过滤。
   */
  needs_review?: boolean
  q?: string
}

export interface Prerequisite {
  kp_id: string
  name: string
  relation_type: RelationType
  reason: string
  confidence: number
}

export interface Example {
  id: string
  question_type: QuestionType
  stem_md: string
  options_json: string[] | null
  answer_md: string
  analysis_md: string
  difficulty: Difficulty
  source_page: number
}

export interface Misconception {
  id: string
  description: string
  cause: string
  remedy: string
  source: 'human' | 'ai'
  confidence: number
}

export interface KnowledgePointDetail extends KnowledgePoint {
  prerequisites: Prerequisite[]
  examples: Example[]
  misconceptions: Misconception[]
}

export interface GraphNode {
  id: string
  name: string
  difficulty: Difficulty
  chapter_id: string
  section_id: string
  needs_review: boolean
}

export interface GraphEdge {
  source: string
  target: string
  relation_type: RelationType
}

export interface GraphStats {
  node_count: number
  edge_count: number
  cycle_count: number
  pruned_count: number
  conflict_count: number
  hard_edge_count: number
  soft_edge_count: number
}

export interface KnowledgeGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  stats: GraphStats
}

export interface GraphQuery {
  material_id?: string
  chapter_id?: string
  max_nodes?: number
}

export interface LearningPathStep {
  order: number
  kp_id: string
  name: string
  difficulty: Difficulty
  /** 来自前置边的 reason（P10 产出），前端逐条展示 —— 让排序可解释 */
  reason: string
  is_start_point: boolean
}

export interface GapPrerequisite {
  kp_id: string
  name: string
  depth: number
  reason: string
}

export interface GapLikely {
  kp_id: string
  name: string
  evidence: string
  source: { material_id: string; page: number }
}

/**
 * `GET /api/knowledge-points/{id}/gap-analysis` 的查询参数（api-spec §4.4，v1.3）。
 *
 * `student_evidence` 是**可重复**的参数，传的是 `kp_misconceptions.id`：
 * ```
 * ?student_evidence=mis_a&student_evidence=mis_b
 * ```
 * 传了它，命中的误区会纳入「最可能断层」的排序依据。
 * ⚠️ **无效值会被忽略而不是报错** —— 它只影响排序精度，不该让整个请求失败，
 * 所以前端**不需要预先校验**这些 id。
 */
export interface GapAnalysisQuery {
  student_evidence?: string[]
}

/** 卡点根因回溯（F3.8 / api-spec §4.4） */
export interface GapAnalysis {
  target_kp: { kp_id: string; name: string }
  hard_prerequisites: GapPrerequisite[]
  likely_gap: GapLikely | null
  suggestion: string
}

export type ExportFormat = 'json' | 'csv'

/**
 * 导出条目（`GET /api/export/knowledge-points`）—— 扁平结构、**含溯源列**，
 * 便于用 Excel 直接核对。字段名与 `backend/app/schemas/report.py::ExportKpOut`
 * 及 `tests/test_schemas.py` 的钉表逐字一致（16 个字段）。
 *
 * ⚠️ `format=csv` 时是**非 JSON 响应**：请求标识走 `X-Request-ID` 响应头，
 * 失败时仍返回 JSON 包封（见 `REQUEST_ID_HEADER`）。
 */
export interface ExportKpOut {
  id: string
  name: string
  summary_md: string
  /** 后端为朴素整数，未收窄到 1–5 */
  difficulty: number
  difficulty_reason: string | null
  kp_type: string
  chapter_number: string | null
  chapter_title: string
  section_number: string | null
  section_title: string
  source_material_id: string
  source_material_name: string
  source_page: number | null
  /** 原文引用 —— 导出件里「可核对」的关键列 */
  source_quote: string
  prerequisite_count: number
  needs_review: boolean
}

/* ------------------------------------------------------------------ *
 * 5. 质量报告（api-spec §4.6）
 * ------------------------------------------------------------------ */

export interface QualityReport {
  materials: {
    total: number
    done: number
    failed: number
    avg_quality_score: number
  }
  knowledge_points: {
    total: number
    structure_complete_rate: number
    five_field_complete_rate: number
    grounding_rate: number
    needs_review_count: number
  }
  graph: {
    edge_count: number
    cycle_count: number
    pruned_count: number
    conflict_count: number
    reason_complete_rate: number
    prerequisite_sampling_pass_rate: number
  }
  qa: {
    session_count: number
    turn_count: number
    grounded_rate: number
    refuse_count: number
  }
}

/* ------------------------------------------------------------------ *
 * 6. 答疑（Stage 3，api-spec §5）—— D8 落地，此处先冻结契约
 * ------------------------------------------------------------------ */

export type SocraticState = 'S0_RETRIEVE' | 'S1_PROBE' | 'S2_HINT1' | 'S3_HINT2' | 'S4_EXPLAIN' | 'REFUSE' | 'CONFIRM'
export type TurnType = 'probe' | 'hint1' | 'hint2' | 'explain' | 'refuse' | 'confirm'

export interface QaSession {
  session_id: string
  material_scope: string[]
  student_label: string
  created_at: string
}

export interface DiagnosisKnowledgePoint {
  kp_id: string
  name: string
  difficulty: Difficulty
}

export interface DiagnosisStuckAt {
  step: string
  evidence_kp_id: string | null
  evidence_misconception_id: string | null
}

export interface Diagnosis {
  knowledge_points: DiagnosisKnowledgePoint[]
  stuck_at: DiagnosisStuckAt
  next_practice: { kp_id: string; task: string }[]
}

export interface QaTurn {
  turn_id: string
  question: string
  turn_type: TurnType
  answer_md: string
  diagnosis: Diagnosis | null
  grounded: boolean
  created_at: string
}

export interface QaSessionDetail extends QaSession {
  turns: QaTurn[]
}

export interface QaState {
  state: SocraticState
  hint_level: number
  consecutive_failures: number
  current_kp_id: string | null
  next_action: TurnType
  explain_threshold: number
}

export interface QaSessionReport {
  session_id: string
  stuck_points: { kp_id: string; name: string; occurrences: number }[]
  suggested_practice: { kp_id: string; task: string }[]
}

/* ------------------------------------------------------------------ *
 * SSE 事件负载（api-spec §5.2）
 *
 * 三条硬约定（v1.3 ③，**已落在后端代码里，不只是文档**）：
 *   1. 每个事件必须带 `id:` 行，且与 `data.seq` **一致** ——
 *      `Last-Event-ID` 断线续推完全依赖它，没有 `id:` 行就没法续推。
 *   2. `id:` 行必须在 `event:` 行**之前**。浏览器按行解析，顺序错了
 *      `Last-Event-ID` 取不到值。
 *   3. `seq` 在**一个会话内单调递增，跨轮次不重置**。
 *
 * 事件顺序固定：`retrieved` → `state` → `delta`* → `diagnosis` → `done`，
 * 其中 **`retrieved` 必须先于任何 `delta`** —— 前端据此**先渲染溯源卡片**，
 * 让「先检索再回答」这件事在界面上可见。
 *
 * 事件模型以后端 `app/schemas/qa.py` 的 5 个 `Sse*Event` 类为准，不要自建一套。
 * ------------------------------------------------------------------ */

export interface SseRetrieved {
  seq: number
  kp_ids: string[]
  block_ids: string[]
  /** 越界时为 true，此时后续 delta 必须是拒答模板 */
  is_out_of_scope: boolean
}

export interface SseState {
  seq: number
  turn_type: TurnType
  state: SocraticState
  hint_level: number
}

export interface SseDelta {
  seq: number
  text: string
}

export interface SseDiagnosis {
  seq: number
  knowledge_points: DiagnosisKnowledgePoint[]
  stuck_at: DiagnosisStuckAt | null
  next_practice: { kp_id: string; task: string }[]
}

export interface SseDone {
  seq: number
  turn_id: string
  latency_ms: number | null
  usage: { input_tokens: number | null; output_tokens: number | null } | null
}

/* ------------------------------------------------------------------ *
 * 7. 任务（api-spec §6）
 * ------------------------------------------------------------------ */

export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'partial'

export interface JobError {
  code: ApiErrorCode
  message: string
}

export interface Job {
  job_id: string
  status: JobStatus
  /** 0–100 */
  progress: number
  /** 必须是人类可读中文，前端直接展示不加工（api-spec §6） */
  stage_detail: string
  result: unknown | null
  error: JobError | null
}

export interface JobQuery {
  target_id?: string
  job_type?: string
}
