import { AlertTriangle, CheckCircle2, CircleHelp } from 'lucide-react'

import { formatMetricValue, metricStatus } from './MetricCard'
import type { MetricSpec } from './MetricCard'

/**
 * 报告总览横幅 —— 深蓝制图材质 + 质量环（Learning Atlas v2）。
 * 环的数值是**从四条核心红线的真实达标数算出来的**（达标数 / 4），
 * 不是装饰数字；某条数据暂缺时按未达标计入（保守口径，宁缺毋错）。
 */
export function ReportBanner({ metrics }: { metrics: MetricSpec[] }) {
  const total = metrics.length || 1
  const passed = metrics.filter((spec) => metricStatus(spec) === 'pass').length
  const missing = metrics.filter((spec) => metricStatus(spec) === 'missing').length
  const percent = Math.round((passed / total) * 100)
  const allPass = passed === total && missing === 0

  return (
    <section className="atlas-navy-panel !rounded-2xl grid gap-5 px-6 py-6 sm:px-7 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
      <div
        aria-hidden
        className="atlas-map-grid absolute inset-0 [background-size:27px_27px] [mask-image:linear-gradient(90deg,transparent,black)]"
      />
      <div className="relative z-10">
        <div className="atlas-eyebrow !text-[#aeb9c6]">SYSTEM AUDIT / QUALITY GATES</div>
        <h2 className="mt-2.5 text-2xl font-bold tracking-[-0.03em]">每条结论，都能回到证据。</h2>
        <p className="mt-2 max-w-[460px] text-xs leading-relaxed text-[#b7c1cc]">
          报告展示数据的来源、校验规则与当前状态。风险项优先呈现，未知值不以零代替。
        </p>
      </div>

      <div className="relative z-10 flex items-center gap-5 lg:justify-end">
        {/* 质量环：conic-gradient 按真实达标比例绘制 */}
        <div
          role="img"
          aria-label={`核心红线达标 ${passed}/${total}`}
          className="grid h-[98px] w-[98px] shrink-0 place-items-center rounded-full"
          style={{
            background: `conic-gradient(#d9ed83 0 ${percent}%, rgba(255,255,255,0.12) ${percent}% 100%)`,
          }}
        >
          <div className="grid h-[84px] w-[84px] place-items-center rounded-full bg-atlas-ink text-center">
            <span className="font-serif text-2xl font-semibold text-lime">
              {passed}/{total}
            </span>
          </div>
        </div>
        <div className="max-w-[170px]">
          <span className="block text-xs font-semibold text-lime">
            {allPass ? '核心红线全部达标' : missing > 0 && passed !== total ? '红线数据尚未齐备' : '存在未达标红线'}
          </span>
          <span className="mt-1.5 block text-[10px] leading-relaxed text-[#aab6c4]">
            质量环 = 四条核心红线的达标数 / 4；暂缺按未达标计。
          </span>
        </div>
      </div>
    </section>
  )
}

const STATUS_ICON = {
  pass: CheckCircle2,
  fail: AlertTriangle,
  missing: CircleHelp,
  info: CircleHelp,
} as const

const STATUS_TEXT = {
  pass: '达标',
  fail: '未达标',
  missing: '暂缺',
  info: '观测项',
} as const

const STATUS_COLOR = {
  pass: '#15803d',
  fail: '#dc2626',
  missing: '#94a3b8',
  info: '#64748b',
} as const

/** 核心红线指标带：四个单元格 + 细进度条（数值只来自报告接口） */
export function MetricsStrip({ metrics }: { metrics: MetricSpec[] }) {
  return (
    <section
      aria-label="核心红线指标"
      className="grid grid-cols-1 divide-y divide-[#cbc4b8] border-y border-[#cbc4b8] bg-atlas-sheet/55 sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4"
    >
      {metrics.map((spec) => {
        const status = metricStatus(spec)
        const Icon = STATUS_ICON[status]
        const color = STATUS_COLOR[status]
        const width =
          status === 'missing'
            ? 0
            : spec.compare === 'eq'
              ? 100
              : spec.rate && typeof spec.value === 'number'
                ? Math.max(0, Math.min(100, spec.value * 100))
                : 100
        return (
          <div key={spec.key} className="px-4 py-3.5">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-atlas-muted">
              {spec.redLine ?? spec.label}
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-serif text-xl font-semibold leading-none tracking-tight" style={{ color }}>
                {formatMetricValue(spec)}
              </span>
              <span className="text-xs text-atlas-muted">{spec.targetText}</span>
            </div>
            <div className="mt-1 flex items-center gap-1 text-xs font-medium" style={{ color }}>
              <Icon className="h-3 w-3" aria-hidden />
              {STATUS_TEXT[status]}
            </div>
            <div className="mt-2 h-[3px] overflow-hidden rounded-full bg-[#ddd8cd]" role="presentation">
              <div
                className="h-full rounded-full transition-[width] duration-300"
                style={{ width: `${width}%`, backgroundColor: color }}
              />
            </div>
          </div>
        )
      })}
    </section>
  )
}
