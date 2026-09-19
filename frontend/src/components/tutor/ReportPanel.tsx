import { RefreshCw, Repeat, Stethoscope } from 'lucide-react'

import { Tag } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { InlineError, Spinner } from '@/components/ui/Feedback'
import type { SessionReportOut } from '@/lib/types'

/**
 * 会话诊断报告 —— `GET /api/qa/sessions/{id}/report`。
 * 把整段会话的卡点按出现次数汇总，并给出建议练习清单（跨轮次的「下一步该练什么」）。
 */
export function ReportPanel({
  report,
  loading,
  error,
  enabled,
  onRefresh,
}: {
  report: SessionReportOut | null
  loading: boolean
  error: string | null
  enabled: boolean
  onRefresh: () => void
}) {
  return (
    <section className="xizhi-card">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <Stethoscope className="h-3.5 w-3.5 text-brand-600" aria-hidden />
          <h2 className="text-sm font-semibold text-slate-800">会话诊断报告</h2>
          {loading && <Spinner className="h-3 w-3" />}
        </div>
        <Button
          variant="ghost"
          size="sm"
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          disabled={!enabled || loading}
          onClick={onRefresh}
        >
          刷新
        </Button>
      </header>

      <div className="space-y-3 p-4">
        {!enabled ? (
          <p className="text-xs leading-relaxed text-slate-400">
            会话开始后，这里会汇总整场练习中反复卡住的知识点。
          </p>
        ) : error ? (
          <InlineError>{error}</InlineError>
        ) : report ? (
          <>
            <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
                <Repeat className="h-3 w-3" aria-hidden />
                卡点汇总（出现次数）
              </div>
              {report.stuck_points.length > 0 ? (
                <ul className="space-y-1.5">
                  {report.stuck_points.map((point) => (
                    <li
                      key={point.kp_id}
                      className="flex items-center justify-between rounded-md border border-slate-200 px-2 py-1.5"
                    >
                      <span className="min-w-0 truncate text-xs text-slate-700" title={point.name}>
                        {point.name}
                      </span>
                      <span className="shrink-0 text-[11px] text-slate-500">
                        ×{point.occurrences}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-slate-400">本场还没有记录到卡点。</p>
              )}
            </div>

            <div>
              <div className="mb-1.5 text-[11px] font-medium text-slate-500">建议练习汇总</div>
              {/* ⚠️ 字段名是 suggested_practices（复数）—— 写成单数会静默拿到 undefined 并崩在这里 */}
              {report.suggested_practices.length > 0 ? (
                <ul className="space-y-1.5">
                  {report.suggested_practices.map((item, index) => (
                    <li key={`${item.kp_id}-${index}`} className="space-y-1">
                      <p className="text-xs leading-relaxed text-slate-700">{item.task}</p>
                      <Tag>{item.kp_id}</Tag>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-slate-400">本场还没有建议练习。</p>
              )}
            </div>
          </>
        ) : (
          <Spinner className="h-3.5 w-3.5" />
        )}
      </div>
    </section>
  )
}
