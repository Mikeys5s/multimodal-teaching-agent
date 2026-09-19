import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import { JobStatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ProgressBar, Spinner } from '@/components/ui/Feedback'
import type { Job, JobStatus } from '@/lib/types'

const TERMINAL_STATUSES: JobStatus[] = ['done', 'failed', 'partial']

export interface ActiveUpload {
  job_id: string
  /** 一行标题（文件名或任务说明），超长会截断，完整内容进 title */
  filename: string
  /** 可选：后端返回的预计耗时（秒）。仅用于展示，前端不据此推算剩余时间 */
  estimated_seconds?: number
  /** 可选：标题右侧的补充说明，如「3 份素材」 */
  hint?: string
}

export interface JobProgressPanelProps {
  items: ActiveUpload[]
  jobs: Record<string, Job>
  onDismiss: () => void
  /** 面板标题，默认「解析进度」 */
  title?: string
  /** failed 时的重试入口（按 job_id 回调） */
  onRetry?: (jobId: string) => void
  /** 任务终结后的补充内容（抽取任务的「去知识图谱」引导就走这里） */
  renderAfter?: (job: Job | undefined, item: ActiveUpload) => ReactNode
  /** 是否在仍有任务运行时也允许收起，默认 false（仅全部终结后出现收起按钮） */
  dismissibleWhileRunning?: boolean
  /** 收起按钮文案，默认「收起」 */
  dismissLabel?: string
  /** 拿不到 stage_detail 时的占位文案，默认「等待后端返回进度…」 */
  waitingLabel?: string
}

/**
 * `estimated_seconds` 是**后端口径**，前端只做单位换算，不据此推算剩余时间。
 * 秒数原样放在 title 里，方便核对，也避免"看起来像自己算的"。
 */
function formatEstimate(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '耗时由后端估算'
  if (seconds < 90) return `预计约 ${Math.round(seconds)} 秒（后端估算）`
  return `预计约 ${Math.round(seconds / 60)} 分钟（后端估算）`
}

/**
 * 任务进度面板（api-spec §6：stage_detail 为人类可读中文，前端直接展示不加工）。
 * 这是"进度可见"这条用户体验要求的落点（SPEC §5.1 F1.7）。
 *
 * 同时服务两类任务：素材解析（上传 / 重试）与知识点抽取（可能跑几十分钟）。
 * 后者的差异点都在可选 props 上：预计耗时、失败重试、终结后的下一步引导。
 */
export function JobProgressPanel({
  items,
  jobs,
  onDismiss,
  title = '解析进度',
  onRetry,
  renderAfter,
  dismissibleWhileRunning = false,
  dismissLabel = '收起',
  waitingLabel = '等待后端返回进度…',
}: JobProgressPanelProps) {
  if (items.length === 0) return null

  const allSettled = items.every((item) => {
    const status = jobs[item.job_id]?.status
    return status !== undefined && TERMINAL_STATUSES.includes(status)
  })

  return (
    <div className="xizhi-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium text-slate-700">
          {title}
          <span className="ml-2 text-xs font-normal text-slate-400">{items.length} 个任务</span>
        </div>
        {(allSettled || dismissibleWhileRunning) && (
          <button className="text-xs text-slate-400 hover:text-slate-600" onClick={onDismiss}>
            {dismissLabel}
          </button>
        )}
      </div>

      <ul className="space-y-3">
        {items.map((item) => {
          const job = jobs[item.job_id]
          const status = job?.status ?? 'pending'
          const progress = job?.progress ?? 0
          const isFailed = status === 'failed'
          const isPartial = status === 'partial'
          const isDone = status === 'done'
          const isSettled = TERMINAL_STATUSES.includes(status)

          return (
            <li key={item.job_id} className="space-y-1.5">
              <div className="flex items-center gap-2">
                {isFailed ? (
                  <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" aria-hidden />
                ) : isDone ? (
                  <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" aria-hidden />
                ) : isPartial ? (
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
                ) : (
                  <Spinner className="h-3.5 w-3.5 shrink-0" />
                )}
                <span className="min-w-0 flex-1 truncate text-xs text-slate-600" title={item.filename}>
                  {item.filename}
                </span>
                {item.hint && (
                  <span className="shrink-0 text-[11px] text-slate-400">{item.hint}</span>
                )}
                <JobStatusBadge status={status} />
                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-slate-400">
                  {Math.round(progress)}%
                </span>
              </div>

              {!isSettled && <ProgressBar value={progress} />}

              {/* ★ stage_detail：后端保证是可读中文，原文照搬 —— 不拼接、不解析、不截断 */}
              <div className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-slate-700">
                {job?.stage_detail?.trim() ? job.stage_detail : waitingLabel}
              </div>

              <div className="flex flex-wrap items-center gap-x-3 text-[11px] text-slate-400">
                {!isSettled && item.estimated_seconds !== undefined && (
                  <span title={`后端估算 ${item.estimated_seconds} 秒`}>
                    {formatEstimate(item.estimated_seconds)}
                  </span>
                )}
                {/* 任务 ID 留着做「报障可核对」，样式压到最低，不跟进度文案抢注意力 */}
                <span className="text-slate-300" title="任务 ID">
                  {item.job_id}
                </span>
              </div>

              {/*
                ⚠️ 失败原因是 `error_message`（**字符串**），不是 `{ code, message }` 对象。
                照旧写法读 `job.error?.message` 会永远为 undefined ——
                结果是「任务失败了但界面上什么都不显示」，还不报错。
              */}
              {isFailed && job?.error_message && (
                <div className="flex items-start gap-1.5 rounded-lg border border-red-100 bg-red-50/70 px-2.5 py-1.5">
                  <span className="mt-px shrink-0 text-[11px] font-medium text-red-500">失败</span>
                  <span className="text-xs leading-relaxed text-red-700">{job.error_message}</span>
                </div>
              )}

              {isFailed && onRetry && (
                <div className="pt-0.5">
                  <Button variant="secondary" size="sm" onClick={() => onRetry(item.job_id)}>
                    重试
                  </Button>
                </div>
              )}

              {isSettled && renderAfter?.(job, item)}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
