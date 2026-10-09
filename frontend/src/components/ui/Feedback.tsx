import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from './Button'

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return <Loader2 className={`${className} animate-spin text-slate-400`} aria-hidden />
}

export function LoadingState({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Spinner />
      {label}
    </div>
  )
}

/**
 * 统一状态布局：简洁图标 + 明确标题 + 一句解释 + 一个有效下一步。
 * 空数据不伪装成错误；失败不伪装成空数据。
 */
export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-100">
        <Inbox className="h-6 w-6 text-slate-400" aria-hidden />
      </div>
      <div className="mt-1 text-sm font-medium text-slate-700">{title}</div>
      {description && <div className="max-w-md text-[13px] leading-5 text-slate-500">{description}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

/** 错误态：message 来自后端，已是可读中文，直接展示；需要处理的错误不自动消失 */
export function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 rounded-xl border border-danger-line bg-danger-soft py-10 text-center"
      role="alert"
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-white">
        <AlertTriangle className="h-5 w-5 text-danger" aria-hidden />
      </div>
      <div className="max-w-lg px-4 text-sm text-danger">{message}</div>
      {onRetry && (
        <Button variant="secondary" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={onRetry}>
          重试
        </Button>
      )}
    </div>
  )
}

export function InlineError({ children }: { children: ReactNode }) {
  return (
    <div
      className="flex items-start gap-2 rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-[13px] leading-5 text-danger"
      role="alert"
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-hidden />
      <span>{children}</span>
    </div>
  )
}

/** 警告态（非致命）：用于「契约漂移」这类必须让人看见、但不该阻断流程的情况 */
export function InlineWarning({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-[13px] leading-5 text-warning">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
      <span>{children}</span>
    </div>
  )
}

/** 进度条：只在后端提供真实百分比时使用 */
export function ProgressBar({ value, className = '' }: { value: number; className?: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)))
  return (
    <div
      className={`h-1.5 w-full overflow-hidden rounded-full bg-slate-100 ${className}`}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className="h-full rounded-full bg-brand-600 transition-[width] duration-300"
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}

/** 不定进度指示：无真实百分比时使用，不伪造百分数 */
export function IndeterminateBar({ className = '' }: { className?: string }) {
  return (
    <div
      className={`relative h-1.5 w-full overflow-hidden rounded-full bg-slate-100 ${className}`}
      role="status"
      aria-label="进行中"
    >
      <div className="absolute inset-y-0 w-1/3 animate-[xizhi-indeterminate_1.2s_ease-in-out_infinite] rounded-full bg-brand-600" />
      <style>{`@keyframes xizhi-indeterminate{0%{left:-33%}100%{left:100%}}`}</style>
    </div>
  )
}
