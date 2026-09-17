import { request, requestText } from './api'
import type {
  Block,
  Capabilities,
  ExportFormat,
  GapAnalysis,
  Health,
  Job,
  JobQuery,
  KnowledgeGraph,
  KnowledgePoint,
  KnowledgePointDetail,
  KnowledgePointQuery,
  LearningPathStep,
  Material,
  MaterialQuery,
  Outline,
  Paginated,
  QualityReport,
  QaSession,
  QaSessionDetail,
  QaSessionReport,
  QaState,
  Question,
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
 * 全部 27 个端点（api-spec §7）。函数名与端点一一对应，便于前端按路由接入。
 * 注意：/qa/sessions/{id}/ask 是 SSE 流式接口，不走此模块，见 lib/sse.ts（D8 实现）。
 */
export const api = {
  /* ---------------- 2. 健康检查与元信息 ---------------- */
  health: () => request<Health>('/health'),
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
  getMarkdown: (id: string) => requestText(`/materials/${id}/markdown`),
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
  getLearningPath: (kpId: string) =>
    request<LearningPathStep[]>('/learning-path', { query: { kp_id: kpId } }),
  getGapAnalysis: (kpId: string, studentEvidence?: string) =>
    request<GapAnalysis>(`/knowledge-points/${kpId}/gap-analysis`, {
      query: { student_evidence: studentEvidence },
    }),
  exportKnowledgePoints: (format: ExportFormat) =>
    requestText('/export/knowledge-points', { query: { format } }),

  /* ---------------- 质量报告 ---------------- */
  getQualityReport: () => request<QualityReport>('/report/quality'),

  /* ---------------- 5. 答疑（Stage 3） ---------------- */
  createQaSession: (body: CreateQaSessionRequest) =>
    request<QaSession>('/qa/sessions', { method: 'POST', body }),
  getQaSession: (id: string) => request<QaSessionDetail>(`/qa/sessions/${id}`),
  getQaState: (id: string) => request<QaState>(`/qa/sessions/${id}/state`),
  getQaReport: (id: string) => request<QaSessionReport>(`/qa/sessions/${id}/report`),
  deleteQaSession: (id: string) => request<void>(`/qa/sessions/${id}`, { method: 'DELETE' }),

  /* ---------------- 6. 任务 ---------------- */
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  listJobs: (q: JobQuery = {}) =>
    request<Paginated<Job>>('/jobs', {
      query: { target_id: q.target_id, job_type: q.job_type },
    }),
}

export type Api = typeof api
