import { AlertTriangle, CheckCircle2, CircleHelp, Info } from 'lucide-react'

import { formatMetricValue, metricStatus } from './MetricCard'
import type { MetricSpec } from './MetricCard'
import type { ReportMetrics } from './buildMetrics'

const STATUS_META = {
  pass: { icon: CheckCircle2, text: '达标', cls: 'text-[#328262]' },
  fail: { icon: AlertTriangle, text: '未达标', cls: 'text-danger' },
  missing: { icon: CircleHelp, text: '暂缺', cls: 'text-slate-400' },
  info: { icon: Info, text: '观测项', cls: 'text-slate-500' },
} as const

function AuditRow({ spec }: { spec: MetricSpec }) {
  const status = metricStatus(spec)
  const meta = STATUS_META[status]
  const Icon = meta.icon
  return (
    <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(60px,0.6fr)_minmax(0,0.8fr)_minmax(64px,0.55fr)] items-center gap-2.5 border-b border-[#ece6dc] px-4 py-2.5 text-xs last:border-b-0 sm:px-5">
      <div className="min-w-0">
        <div className="truncate font-medium text-slate-700" title={spec.note ? String(spec.note) : undefined}>
          {spec.redLine ?? spec.label}
        </div>
        {spec.redLine && <div className="mt-0.5 truncate text-[11px] text-atlas-muted">{spec.label}</div>}
      </div>
      <div className="font-serif text-sm font-semibold tabular-nums text-atlas-ink">
        {formatMetricValue(spec)}
      </div>
      <div className="truncate text-[11px] text-atlas-muted" title={spec.targetText}>
        {spec.targetText}
      </div>
      <div className={`flex items-center gap-1 font-medium ${meta.cls}`}>
        <Icon className="h-3 w-3 shrink-0" aria-hidden />
        <span className="whitespace-nowrap">{meta.text}</span>
      </div>
    </div>
  )
}

const GROUPS: { key: keyof Omit<ReportMetrics, 'critical'>; title: string; subtitle: string }[] = [
  { key: 'materials', title: '素材解析', subtitle: '解析成功率、失败可见性、质量均分' },
  { key: 'knowledgePoints', title: '知识点', subtitle: '三级结构、溯源覆盖、五要素、待复核' },
  { key: 'graph', title: '知识图谱', subtitle: '环数、边理由完备率、剪枝与冲突可见性' },
  { key: 'qa', title: '答疑辅导', subtitle: '接地率、拒答次数（拒答是能力，不是缺陷）' },
]

/**
 * 校验清单（暖纸审计表）—— 全部指标按分区成表：检查项 / 当前值 / 验收条件 / 状态。
 * 未达标显式标红并配文字；null 显示「暂缺」而不是 0（保留 unknown 语义）。
 */
export function AuditSheet({ metrics }: { metrics: ReportMetrics }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-atlas-line bg-atlas-sheet">
      <div className="flex items-center justify-between gap-3 border-b border-atlas-line bg-atlas-paper2 px-4 py-3 sm:px-5">
        <h3 className="text-sm font-semibold text-atlas-ink">校验清单 / QUALITY GATES</h3>
        <span className="text-[10px] text-atlas-muted">每一项都有可追溯规则</span>
      </div>

      <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(60px,0.6fr)_minmax(0,0.8fr)_minmax(64px,0.55fr)] gap-2.5 border-b border-[#ece6dc] bg-[#faf8f2] px-4 py-2 text-[10px] uppercase tracking-wider text-[#838c94] sm:px-5">
        <span>检查项</span>
        <span>当前值</span>
        <span>验收条件</span>
        <span>状态</span>
      </div>

      {GROUPS.map((group) => (
        <div key={group.key}>
          <div className="border-b border-[#ece6dc] bg-atlas-paper/70 px-4 py-2 sm:px-5">
            <span className="text-xs font-semibold text-atlas-ink">{group.title}</span>
            <span className="ml-2 text-[10px] text-atlas-muted">{group.subtitle}</span>
          </div>
          {metrics[group.key].map((spec) => (
            <AuditRow key={spec.key} spec={spec} />
          ))}
        </div>
      ))}
    </section>
  )
}

/** 读法说明（蓝色 NOTE 面板）：达标不代表没有风险 */
export function ReportNote() {
  return (
    <aside className="relative overflow-hidden rounded-2xl border border-[#c3d0e6] bg-[#e5edfa] p-5">
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-20 -right-20 h-40 w-40 rounded-full border border-[#8ea8d2] shadow-[0_0_0_18px_rgba(49,92,255,0.06)]"
      />
      <div className="atlas-eyebrow !text-[#506b93]">
        <span className="idx">NOTE</span> HOW TO READ
      </div>
      <h3 className="mt-2.5 text-base font-semibold tracking-tight text-[#233a56]">
        达标，不代表没有风险。
      </h3>
      <p className="mt-2 max-w-[230px] text-xs leading-relaxed text-[#586c89]">
        结构指标、溯源覆盖和待复核关系分开呈现。每个状态都有对应的规则和下一步处理方式：
        未达标会显式标红，「暂缺」说明后端尚未产出该值，不以 0 冒充。
      </p>
      <a
        href="#health-self-check"
        className="relative z-10 mt-3 inline-block text-xs font-medium text-brand-600 hover:underline"
      >
        查看部署自检与数据导出 ↗
      </a>
    </aside>
  )
}
