import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { Button } from './Button'

export function Spinner({ className = 'h-4 w-4' }: { className?: string }) {
  return <Loader2 className={`${className} animate-spin text-slate-400`} aria-hidden />
}

export function LoadingState({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <Spinner />
      {label}
    </div>
  )
}

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
      <Inbox className="h-8 w-8 text-slate-300" aria-hidden />
      <div className="text-sm font-medium text-slate-600">{title}</div>
      {description && <div className="max-w-md text-xs text-slate-400">{description}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** 错误态：message 来自后端，已是可读中文，直接展示 */
export function ErrorState({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-red-100 bg-red-50/60 py-10 text-center">
      <AlertTriangle className="h-7 w-7 text-red-400" aria-hidden />
      <div className="max-w-lg text-sm text-red-700">{message}</div>
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
    <div className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50/70 px-3 py-2 text-xs text-red-700">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-400" aria-hidden />
      <span>{children}</span>
    </div>
  )
}

export function ProgressBar({ value, className = '' }: { value: number; className?: string }) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)))
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-slate-100 ${className}`}>
      <div
        className="h-full rounded-full bg-brand-500 transition-[width] duration-300"
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}
