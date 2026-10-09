import type { ReactNode } from 'react'

import { DIFFICULTY_LABEL, STATUS_LABEL, JOB_STATUS_LABEL, SEVERITY_LABEL, difficultyColor } from '@/lib/format'
import type { Difficulty, JobStatus, MaterialStatus, Severity } from '@/lib/types'

export function Badge({
  color,
  children,
  dot = false,
}: {
  color: string
  children: ReactNode
  dot?: boolean
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium"
      style={{ color, backgroundColor: `${color}14`, borderColor: `${color}33` }}
    >
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />}
      {children}
    </span>
  )
}

const MATERIAL_STATUS_COLOR: Record<MaterialStatus, string> = {
  pending: '#94a3b8',
  parsing: '#3b82f6',
  done: '#10b981',
  partial: '#f59e0b',
  failed: '#ef4444',
}

const JOB_STATUS_COLOR: Record<JobStatus, string> = {
  pending: '#94a3b8',
  running: '#3b82f6',
  done: '#10b981',
  partial: '#f59e0b',
  failed: '#ef4444',
}

const SEVERITY_COLOR: Record<Severity, string> = {
  low: '#64748b',
  medium: '#f59e0b',
  high: '#ef4444',
}

export function StatusBadge({ status }: { status: MaterialStatus }) {
  return (
    <Badge color={MATERIAL_STATUS_COLOR[status] ?? '#94a3b8'} dot>
      {STATUS_LABEL[status] ?? status}
    </Badge>
  )
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  return (
    <Badge color={JOB_STATUS_COLOR[status] ?? '#94a3b8'} dot>
      {JOB_STATUS_LABEL[status] ?? status}
    </Badge>
  )
}

export function DifficultyBadge({ difficulty }: { difficulty: Difficulty }) {
  return (
    <Badge color={difficultyColor(difficulty)}>
      难度 {difficulty} · {DIFFICULTY_LABEL[difficulty]}
    </Badge>
  )
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge color={SEVERITY_COLOR[severity] ?? '#94a3b8'}>{SEVERITY_LABEL[severity]}风险</Badge>
}

/**
 * 灰色小标签。`title` 可选 —— 用于把「机器标识」（如 `kp_ada1063f_000_000_035`）
 * 收进悬停提示：学生看名字，需要核对的人仍能拿到 id。
 */
export function Tag({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span
      className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600"
      title={title}
    >
      {children}
    </span>
  )
}
