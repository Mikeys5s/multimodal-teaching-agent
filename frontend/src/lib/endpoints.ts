import { request, requestText } from './api'
import type {
  Block,
  Capabilities,
  ExportKpOut,
  GapAnalysis,
  Health,
  Job,
  JobQuery,
  KnowledgeGraph,
  KnowledgePoint,
  KnowledgePointDetail,
  KnowledgePointQuery,
  LearningPathOut,
  LearningPathStep,
  Material,
  MaterialQuery,
  Outline,
  Paginated,
  PragmaOut,
  QaSessionCreated,
  QaState,
  QualityReport,
  Question,
  SessionDetailOut,
  SessionReportOut,
  UploadResult,
} from './types'

export interface ExtractRequest {
  material_ids: string[]
  force?: boolean
}

export interface ExtractAccepted {
  job_id: string
  estimated_seconds: number
}

export interface CreateQaSessionRequest {
  material_scope: string[]
  student_label: string
}

/**
 * 全部 28 个端点（api-spec §7，v1.3）。函数名与端点一一对应，便于前端按路由接入。
 * 注意：/qa/sessions/{id}/ask 是 SSE 流式接口，不走此模块，见 lib/sse.ts（D8 实现）。
 */
export const api = {
  /* ---------------- 2. 健康检查与元信息 ---------------- */
  health: () => request<Health>('/health'),
  /** v1.3 补登记的第 28 个端点：读回实际 SQLite pragma（演示前自检页用） */
  healthPragma: () => request<PragmaOut>('/health/pragma'),
  capabilities: () => request<Capabilities>('/meta/capabilities'),

  /* ---------------- 3. 素材（Stage 1） ---------------- */
  uploadMaterials: (files: File[]) => {
    const fd = new FormData()
    for (const file of files) fd.append('files', file)
    return request<UploadResult>('/materials', { method: 'POST', formData: fd })
  },
  listMaterials: (q: MaterialQuery = {}) =>
    request<Paginated<Material>>('/materials', {
      query: { status: q.status, page: q.page, page_size: q.page_size },
    }),
  getMaterial: (id: string) => request<Material>(`/materials/${id}`),
  listBlocks: (id: string, q: { page_no?: number; block_type?: string } = {}) =>
    request<Block[]>(`/materials/${id}/blocks`, {
      query: { page_no: q.page_no, block_type: q.block_type },
    }),
  /** 整篇拼接 Markdown —— 非 JSON 响应（v1.3）：标识走 `X-Request-ID` 响应头 */
  getMarkdown: (id: string) => requestText(`/materials/${id}/markdown`, {}, 'text/markdown'),
  getOutline: (id: string) => request<Outline>(`/materials/${id}/outline`),
  listQuestions: (id: string) => request<Question[]>(`/materials/${id}/questions`),
  reparseMaterial: (id: string) =>
    request<{ job_id: string }>(`/materials/${id}/reparse`, { method: 'POST' }),
  deleteMaterial: (id: string) => request<void>(`/materials/${id}`, { method: 'DELETE' }),

  /* ---------------- 4. 抽取与知识点（Stage 2） ---------------- */
  extractKnowledge: (body: ExtractRequest) =>
    request<ExtractAccepted>('/extract/knowledge', { method: 'POST', body }),
  listKnowledgePoints: (q: KnowledgePointQuery = {}) =>
    request<Paginated<KnowledgePoint>>('/knowledge-points', {
      query: {
        chapter_id: q.chapter_id,
        section_id: q.section_id,
        material_id: q.material_id,
        difficulty_min: q.difficulty_min,
        difficulty_max: q.difficulty_max,
        kp_type: q.kp_type,
        needs_review: q.needs_review,
        q: q.q,
        page: q.page,
        page_size: q.page_size,
      },
    }),
  getKnowledgePoint: (id: string) => request<KnowledgePointDetail>(`/knowledge-points/${id}`),
  getKnowledgeGraph: (q: { material_id?: string; chapter_id?: string; max_nodes?: number } = {}) =>
    request<KnowledgeGraph>('/knowledge-graph', {
      query: { material_id: q.material_id, chapter_id: q.chapter_id, max_nodes: q.max_nodes },
    }),
  /**
   * 学习路径（api-spec §4.4）。
   *
   * ⚠️ **线上实测（2026-09-19）后端返回的是对象 `{ target_kp_id, steps }`**，而 §4.4 承诺的是
   * **顶层数组** `LearningPathStep[]`。这里做「两种形状都读」的兼容：数组直接用、对象取 `steps`、
   * 都没有则退化为空数组。
   *
   * 不做兼容的后果是**页面崩溃**：`PathTimeline` 会 `for (const step of steps)`，对普通对象抛
   * `steps is not iterable`；且 `steps.length` 为 `undefined`，连「加载中 / 空状态 / 时间线」
   * 三个分支全部落空 —— 白屏且无提示。
   *
   * 已按「以 spec 为准」在 Issue #15 请 P2 收口为数组；收口后本兼容层保留亦无害。
   */
  getLearningPath: async (kpId: string): Promise<LearningPathStep[]> => {
    const data = await request<LearningPathStep[] | LearningPathOut | null>('/learning-path', {
      query: { kp_id: kpId },
    })
    if (Array.isArray(data)) return data
    return data?.steps ?? []
  },
  /**
   * 卡点根因回溯（api-spec §4.4）。
   * `studentEvidence` 是 `kp_misconceptions.id` 列表 —— v1.3 明确为**可重复查询参数**，
   * 会展开成 `?student_evidence=a&student_evidence=b`。
   * 无效 id **被忽略而非报错**（只影响排序精度），所以不需要预先校验。
   */
  getGapAnalysis: (kpId: string, studentEvidence: string[] = []) =>
    request<GapAnalysis>(`/knowledge-points/${kpId}/gap-analysis`, {
      query: { student_evidence: studentEvidence },
    }),
  /**
   * 导出知识点（api-spec §4.5 / 端点 18）。
   * ⚠️ **两个分支的响应性质不同**（已核对 `backend/app/api/report.py`）：
   *   - `format=json` → `application/json` **包封**，走普通 `request`；
   *   - `format=csv`  → 原始 `text/csv`，属 v1.3 的非 JSON 例外（标识走 `X-Request-ID`）。
   * 所以拆成两个函数，避免调用方拿到 string 还是数组要靠猜。
   */
  exportKnowledgePointsJson: () =>
    request<ExportKpOut[]>('/export/knowledge-points', { query: { format: 'json' } }),
  exportKnowledgePointsCsv: () =>
    requestText('/export/knowledge-points', { query: { format: 'csv' } }, 'text/csv'),

  /* ---------------- 质量报告 ---------------- */
  getQualityReport: () => request<QualityReport>('/report/quality'),

  /* ---------------- 5. 答疑（Stage 3） ---------------- */
  /** 创建会话：响应**只有 `session_id`**（不是完整会话对象），详情要再发 getQaSession */
  createQaSession: (body: CreateQaSessionRequest) =>
    request<QaSessionCreated>('/qa/sessions', { method: 'POST', body }),
  getQaSession: (id: string) => request<SessionDetailOut>(`/qa/sessions/${id}`),
  getQaState: (id: string) => request<QaState>(`/qa/sessions/${id}/state`),
  getQaReport: (id: string) => request<SessionReportOut>(`/qa/sessions/${id}/report`),
  deleteQaSession: (id: string) => request<void>(`/qa/sessions/${id}`, { method: 'DELETE' }),

  /* ---------------- 6. 任务 ---------------- */
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  listJobs: (q: JobQuery = {}) =>
    request<Paginated<Job>>('/jobs', {
      query: { target_id: q.target_id, job_type: q.job_type },
    }),
}

export type Api = typeof api
