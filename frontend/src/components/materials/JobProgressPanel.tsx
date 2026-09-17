import { CheckCircle2, XCircle } from 'lucide-react'

import { JobStatusBadge } from '@/components/ui/Badge'
import { ProgressBar } from '@/components/ui/Feedback'
import type { Job } from '@/lib/types'

export interface ActiveUpload {
  job_id: string
  filename: string
}

export interface JobProgressPanelProps {
  items: ActiveUpload[]
  jobs: Record<string, Job>
  onDismiss: () => void
}

/**
 * 解析进度面板（api-spec §6：stage_detail 为人类可读中文，前端直接展示不加工）。
 * 这是"进度可见"这条用户体验要求的落点（SPEC §5.1 F1.7）。
 */
export function JobProgressPanel({ items, jobs, onDismiss }: JobProgressPanelProps) {
  if (items.length === 0) return null

  const allSettled = items.every((item) => {
    const status = jobs[item.job_id]?.status
    return status === 'done' || status === 'failed' || status === 'partial'
  })

  return (
    <div className="xizhi-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium text-slate-700">
          解析进度
          <span className="ml-2 text-xs font-normal text-slate-400">{items.length} 个任务</span>
        </div>
        {allSettled && (
          <button className="text-xs text-slate-400 hover:text-slate-600" onClick={onDismiss}>
            收起
          </button>
        )}
      </div>

      <ul className="space-y-3">
        {items.map((item) => {
          const job = jobs[item.job_id]
          const status = job?.status ?? 'pending'
          const progress = job?.progress ?? 0
          const isFailed = status === 'failed'
          const isDone = status === 'done' || status === 'partial'

          return (
            <li key={item.job_id} className="space-y-1.5">
              <div className="flex items-center gap-2">
                {isDone && !isFailed ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" aria-hidden />
                ) : isFailed ? (
                  <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" aria-hidden />
                ) : null}
                <span className="min-w-0 flex-1 truncate text-xs text-slate-600" title={item.filename}>
                  {item.filename}
                </span>
                <JobStatusBadge status={status} />
                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-slate-400">
                  {Math.round(progress)}%
                </span>
              </div>
              {!isDone && <ProgressBar value={progress} />}
              <div className="text-xs text-slate-400">
                {job?.error?.message ?? job?.stage_detail ?? '等待后端开始解析…'}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
