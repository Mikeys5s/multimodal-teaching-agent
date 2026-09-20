import { AlertTriangle, CheckCircle2, CircleHelp, ShieldCheck } from 'lucide-react'

import { formatMetricValue, isNum, metricStatus } from './MetricCard'
import type { MetricSpec } from './MetricCard'

/**
 * 顶部总览条：把四条最关键的红线（A2-1 三级结构完整率、A2-3 溯源覆盖率、
 * B1-2 DAG 环数、接地率）做成一句话结论 —— **这一页是给评委看的「能否过验收」**。
 */
export function ReportOverview({ metrics }: { metrics: MetricSpec[] }) {
  const failed = metrics.filter((spec) => metricStatus(spec) === 'fail')
  const missing = metrics.filter((spec) => metricStatus(spec) === 'missing')
  const allPass = failed.length === 0 && missing.length === 0

  const tone = allPass
    ? { border: 'border-emerald-200', bg: 'bg-emerald-50/60', text: 'text-emerald-700', accent: '#10b981' }
    : failed.length > 0
      ? { border: 'border-red-200', bg: 'bg-red-50/60', text: 'text-red-700', accent: '#ef4444' }
      : { border: 'border-amber-200', bg: 'bg-amber-50/60', text: 'text-amber-700', accent: '#f59e0b' }

  const verdict = allPass ? '核心红线全部达标，可过验收' : failed.length > 0 ? '存在未达标红线' : '红线数据尚未齐备'
  const detail = allPass
    ? '三级结构完整率、溯源覆盖率、DAG 环数、接地率四项均满足验收口径。'
    : failed.length > 0
      ? `${failed.map((spec) => spec.redLine ?? spec.label).join('、')} 未达标，请在对应环节修正后重新生成报告。`
      : `${missing.map((spec) => spec.redLine ?? spec.label).join('、')} 暂无数据，请先完成前置流程。`

  return (
    <section className={`rounded-xl border ${tone.border} ${tone.bg} p-4`}>
      <div className="flex items-start gap-3">
        {allPass ? (
          <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0" style={{ color: tone.accent }} aria-hidden />
        ) : (
          <AlertTriangle className="mt-0.5 h-6 w-6 shrink-0" style={{ color: tone.accent }} aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <div className={`text-sm font-semibold ${tone.text}`}>{verdict}</div>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-600">{detail}</p>
        </div>
        <span className="hidden items-center gap-1 rounded-full bg-white/70 px-2.5 py-1 text-[11px] font-medium text-slate-600 lg:inline-flex">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          四条核心红线
        </span>
      </div>

      <div className="mt-3 grid grid-cols-4 gap-3">
        {metrics.map((spec) => {
          const status = metricStatus(spec)
          const color = status === 'pass' ? '#10b981' : status === 'fail' ? '#ef4444' : '#94a3b8'
          return (
            <div key={spec.key} className="rounded-lg border border-white/70 bg-white/80 px-3 py-2.5">
              <div className="truncate text-[11px] font-medium text-slate-500">
                {spec.redLine ?? spec.label}
              </div>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className="text-xl font-semibold tabular-nums" style={{ color }}>
                  {formatMetricValue(spec)}
                </span>
                <span className="text-[11px] text-slate-400">{spec.targetText}</span>
              </div>
              <div className="mt-1 flex items-center gap-1 text-[11px] font-medium" style={{ color }}>
                {status === 'pass' && <CheckCircle2 className="h-3 w-3" aria-hidden />}
                {status === 'fail' && <AlertTriangle className="h-3 w-3" aria-hidden />}
                {status === 'missing' && <CircleHelp className="h-3 w-3" aria-hidden />}
                {status === 'pass' ? '达标' : status === 'fail' ? '未达标' : '暂缺'}
              </div>
              {spec.compare === 'eq' && isNum(spec.value) && (
                <div className="mt-1 text-[10px] text-slate-400">必须为 0，当前 {spec.value}</div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
