import type {
  Difficulty,
  JobStatus,
  MaterialStatus,
  ParseMethod,
  Severity,
  SourceType,
  UncertainKind,
} from './types'

/* ---------------- 枚举 → 中文（全部直接展示给用户） ---------------- */

export const STATUS_LABEL: Record<MaterialStatus, string> = {
  pending: '待处理',
  parsing: '解析中',
  done: '已完成',
  failed: '失败',
  partial: '部分完成',
}

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  pending: '排队中',
  running: '进行中',
  done: '完成',
  failed: '失败',
  partial: '部分完成',
}

export const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  pdf_text: '文本版 PDF',
  pdf_scan: '扫描版 PDF',
  docx: 'Word 文档',
  pptx: 'PPT 演示',
  image: '图片',
}

export const PARSE_METHOD_LABEL: Record<ParseMethod, string> = {
  text_extract: '文本抽取',
  multimodal_llm: '多模态识别',
  ocr: '本地 OCR',
  asr: '语音转写',
}

export const UNCERTAIN_KIND_LABEL: Record<UncertainKind, string> = {
  ocr_low_confidence: '识别置信度偏低',
  missing_field: '字段缺失',
  structure_unclear: '结构不清晰',
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

export const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  1: '入门',
  2: '基础',
  3: '进阶',
  4: '较难',
  5: '困难',
}

/* ---------------- 格式化 ---------------- */

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  const mb = kb / 1024
  return `${mb.toFixed(1)} MB`
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}`
}

export function formatPercent(ratio: number, digits = 1): string {
  if (!Number.isFinite(ratio)) return '—'
  return `${(ratio * 100).toFixed(digits)}%`
}

export function formatScore(score: number): string {
  if (!Number.isFinite(score)) return '—'
  return score.toFixed(2)
}

/** 难度色阶（与 tailwind.config.js 的 difficulty token 对齐） */
export const DIFFICULTY_COLOR: Record<Difficulty, string> = {
  1: '#10b981',
  2: '#84cc16',
  3: '#f59e0b',
  4: '#f97316',
  5: '#ef4444',
}

export function difficultyColor(d: Difficulty): string {
  return DIFFICULTY_COLOR[d] ?? '#94a3b8'
}
