/**
 * 全局类型定义 —— 严格对齐 docs/api-spec.md v1.2。
 * 任何字段改动都必须先改 api-spec，再改这里（SPEC §9.2 接口冻结纪律：
 * 允许「新增端点 / 新增可选字段」，不允许改已有字段名或类型）。
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

export interface Question {
  id: string
  question_type: QuestionType
  stem_md: string
  options_json: string[] | null
  answer_md: string | null
  analysis_md?: string | null
  kp_id?: string | null
  source_page?: number | null
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

/** 卡点根因回溯（F3.8 / api-spec §4.4） */
export interface GapAnalysis {
  target_kp: { kp_id: string; name: string }
  hard_prerequisites: GapPrerequisite[]
  likely_gap: GapLikely | null
  suggestion: string
}

export type ExportFormat = 'json' | 'csv'

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

/* SSE 事件负载（api-spec §5.2） */
export interface SseRetrieved {
  kp_ids: string[]
  block_ids: string[]
  is_out_of_scope: boolean
}

export interface SseState {
  turn_type: TurnType
  state: SocraticState
  hint_level: number
}

export interface SseDelta {
  text: string
}

export interface SseDone {
  turn_id: string
  latency_ms: number
  usage: { input_tokens: number; output_tokens: number }
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
