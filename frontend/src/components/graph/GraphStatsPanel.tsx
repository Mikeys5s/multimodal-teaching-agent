import { ShieldCheck } from 'lucide-react'

import type { GraphStats } from '@/lib/types'

export interface GraphStatsPanelProps {
  stats: GraphStats
  /** 当前视图（应用客户端筛选后）的节点/边数量 */
  viewNodeCount: number
  viewEdgeCount: number
  filtered: boolean
}

function StatCell({
  caption,
  value,
  note,
  tone = 'ink',
}: {
  caption: string
  value: React.ReactNode
  note: string
  tone?: 'ink' | 'success' | 'warning' | 'danger'
}) {
  const toneClass =
    tone === 'success'
      ? 'text-success'
      : tone === 'warning'
        ? 'text-warning'
        : tone === 'danger'
          ? 'text-danger'
          : 'text-atlas-ink'
  return (
    <div className="min-w-0 px-4 py-2.5 sm:px-5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-atlas-muted">{caption}</div>
      <div className={['mt-1 flex items-baseline gap-1.5 font-serif text-xl font-semibold leading-none', toneClass].join(' ')}>
        {value}
        <span className="font-sans text-xs font-normal text-atlas-muted">{note}</span>
      </div>
    </div>
  )
}

/**
 * 图谱统计顶线条 —— 本页的核心信任信号（api-spec §4.4）。
 * 面向教师/学习者用中文概念名（不再直接展示 `cycle_count` 等工程字段名）：
 * 「检出了 N 条会成环的边并已剪除」比只写「环数 0」更有说服力 ——
 * 前者证明系统真的在逐边做环检测，而不只是恰好没出错。
 */
export function GraphStatsPanel({ stats, viewNodeCount, viewEdgeCount, filtered }: GraphStatsPanelProps) {
  const acyclic = stats.cycle_count === 0

  return (
    <section
      className="flex flex-wrap items-stretch divide-x divide-[#ded8cb] rounded-xl border border-[#cfc9bd] bg-atlas-sheet/80"
      aria-label="图谱健康指标"
    >
      <StatCell
        caption="依赖环数"
        value={
          acyclic ? (
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="h-4 w-4" aria-hidden />
              0
            </span>
          ) : (
            stats.cycle_count
          )
        }
        note={acyclic ? '必须为 0 · 已达成' : '存在环，无法拓扑排序'}
        tone={acyclic ? 'success' : 'danger'}
      />
      <StatCell
        caption="已剪除的成环边"
        value={stats.pruned_count}
        note="逐边检测后剪除 · 审计可见"
        tone={stats.pruned_count > 0 ? 'warning' : 'ink'}
      />
      <StatCell
        caption="冲突边（结构-语义）"
        value={stats.conflict_count}
        note="不静默丢弃 · 待复核"
        tone={stats.conflict_count > 0 ? 'warning' : 'ink'}
      />
      <StatCell
        caption="当前视图"
        value={viewNodeCount}
        note={`节点 · ${viewEdgeCount} 边${filtered ? '（已应用筛选）' : ''}`}
      />
    </section>
  )
}
