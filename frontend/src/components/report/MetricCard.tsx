import { AlertTriangle, CheckCircle2, CircleHelp, Info, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'

/** 判定口径：gte = 达到目标值即达标；eq = 必须精确等于目标值（如环数必须为 0）；info = 观测项，无红线 */
export type Compare = 'gte' | 'eq' | 'info'
export type MetricStatus = 'pass' | 'fail' | 'info' | 'missing'

export interface MetricSpec {
  key: string
  /** 指标中文名（可带后端字段名） */
  label: string
  /** 验收红线编号与名称，如「A2-1 三级结构完整率」；观测项传 null */
  redLine: string | null
  /** 验收口径文字（直接展示给评委） */
  targetText: string
  /** 后端原始值；可能为 null（后端未产出时） */
  value: number | null | undefined
  target?: number
  compare: Compare
  /** 比率型（0–1）：展示为百分比，进度条按比率绘制 */
  rate?: boolean
  /** 计数型指标的可选相对规模（0–1），让进度条有意义（如 done/total） */
  ratio?: number
  note?: ReactNode
  /** 是否为核心红线（顶部总览采用） */
  critical?: boolean
}

/** 只认「真实数字」，null / undefined / NaN 一律按「暂缺」处理，不当作 0 */
export function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function metricStatus(spec: MetricSpec): MetricStatus {
  if (spec.compare === 'info') return isNum(spec.value) ? 'info' : 'missing'
  if (!isNum(spec.value)) return 'missing'
  const target = spec.target ?? 0
  if (spec.compare === 'gte') return spec.value >= target ? 'pass' : 'fail'
  return spec.value === target ? 'pass' : 'fail'
}

export function formatRate(ratio: number): string {
  return `${Number((ratio * 100).toFixed(1))}%`
}

export function formatMetricValue(spec: MetricSpec): string {
  if (!isNum(spec.value)) return '暂缺'
  return spec.rate ? formatRate(spec.value) : String(spec.value)
}

const COLOR = {
  pass: '#10b981',
  fail: '#ef4444',
  info: '#64748b',
  missing: '#cbd5e1',
} as const

const STATUS_TEXT: Record<MetricStatus, string> = {
  pass: '达标',
  fail: '未达标',
  info: '观测项',
  missing: '暂缺',
}

function barWidth(spec: MetricSpec, status: MetricStatus): number {
  if (status === 'missing') return 0
  if (spec.compare === 'eq') return 100 // 门禁型：达标即整条亮起
  if (spec.rate && isNum(spec.value)) return Math.max(0, Math.min(100, spec.value * 100))
  if (isNum(spec.ratio)) return Math.max(0, Math.min(100, spec.ratio * 100))
  return 100 // 纯计数且无规模参照：整条中性底
}

function StatusIcon({ status }: { status: MetricStatus }) {
  const cls = 'h-3.5 w-3.5 shrink-0'
  if (status === 'pass') return <CheckCircle2 className={cls} aria-hidden />
  if (status === 'fail') return <AlertTriangle className={cls} aria-hidden />
  if (status === 'missing') return <CircleHelp className={cls} aria-hidden />
  return <Info className={cls} aria-hidden />
}

/**
 * 单条指标卡：**数值 + 进度条 + 对应验收红线**三件套。
 * 未达标一律标红并写明「未达标」；达标给绿色通过标记；null 显示「暂缺」而不是 0。
 */
export function MetricCard({ spec }: { spec: MetricSpec }) {
  const status = metricStatus(spec)
  const color = COLOR[status]
  const width = barWidth(spec, status)

  return (
    <div
      className={[
        'rounded-xl border p-3.5',
        status === 'fail' ? 'border-red-200 bg-red-50/50' : 'border-slate-200 bg-white',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
            {spec.redLine ? (
              <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-brand-600" aria-hidden />
            ) : null}
            <span className="truncate">{spec.redLine ?? spec.label}</span>
          </div>
          {spec.redLine && <div className="mt-0.5 truncate text-[11px] text-slate-400">{spec.label}</div>}
        </div>
        <span
          className="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium"
          style={{ color, backgroundColor: `${color}18` }}
        >
          <StatusIcon status={status} />
          {STATUS_TEXT[status]}
        </span>
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        <span
          className="text-2xl font-semibold tabular-nums"
          style={{ color: status === 'missing' ? '#94a3b8' : color }}
        >
          {formatMetricValue(spec)}
        </span>
        <span className="text-[11px] text-slate-500">{spec.targetText}</span>
      </div>

      {/* 进度条：自己用 div 画，不引图表库 */}
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100" role="presentation">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${width}%`, backgroundColor: color }}
        />
      </div>

      {spec.note && <p className="mt-2 text-[11px] leading-relaxed text-slate-500">{spec.note}</p>}
      {status === 'fail' && (
        <p className="mt-1.5 text-[11px] font-medium leading-relaxed text-red-600">
          未达标：当前值未满足验收红线，请回到对应环节核对。
        </p>
      )}
    </div>
  )
}

/** 分区卡片外壳：标题 + 说明 + 指标网格 */
export function MetricSection({
  title,
  subtitle,
  metrics,
}: {
  title: string
  subtitle: string
  metrics: MetricSpec[]
}) {
  return (
    <section className="xizhi-card">
      <header className="flex items-baseline gap-3 border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        <span className="text-xs text-slate-400">{subtitle}</span>
      </header>
      <div className="grid grid-cols-2 gap-3 p-4 lg:grid-cols-3">
        {metrics.map((spec) => (
          <MetricCard key={spec.key} spec={spec} />
        ))}
      </div>
    </section>
  )
}
