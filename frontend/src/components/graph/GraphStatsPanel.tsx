import { AlertTriangle, GitBranch, Scissors, ShieldCheck } from 'lucide-react'

import type { GraphStats } from '@/lib/types'

export interface GraphStatsPanelProps {
  stats: GraphStats
  /** 当前视图（应用客户端筛选后）的节点/边数量 */
  viewNodeCount: number
  viewEdgeCount: number
  filtered: boolean
}

/**
 * 图谱统计面板 —— 本页的核心信任信号（api-spec §4.4）。
 * `cycle_count` 突出显示为 0；并同时给出 `pruned_count`（因成环被剪除的边数）
 * 与 `conflict_count`（结构-语义冲突边数）：**「检出了 N 条会成环的边并已剪除」
 * 比只写「环数 0」更有说服力** —— 前者证明系统真的在检查，而不是恰好没出错。
 */
export function GraphStatsPanel({ stats, viewNodeCount, viewEdgeCount, filtered }: GraphStatsPanelProps) {
  const acyclic = stats.cycle_count === 0

  return (
    <section className="grid grid-cols-12 gap-4">
      {/* 核心指标：环数 */}
      <div
        className={[
          'col-span-4 rounded-xl border p-4',
          acyclic ? 'border-emerald-200 bg-emerald-50/60' : 'border-red-200 bg-red-50/60',
        ].join(' ')}
      >
        <div className={['flex items-center gap-1.5 text-xs font-medium', acyclic ? 'text-emerald-700' : 'text-red-700'].join(' ')}>
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          依赖环数 cycle_count
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span
            className={['text-4xl font-semibold tabular-nums', acyclic ? 'text-emerald-600' : 'text-red-600'].join(' ')}
          >
            {stats.cycle_count}
          </span>
          {acyclic && (
            <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-[11px] font-medium text-white">
              DAG 不变量成立
            </span>
          )}
        </div>
        <p className="mt-2 text-xs leading-relaxed text-slate-600">
          {acyclic
            ? '「知识点依赖无环」是硬性工程指标：只要有一条环，「先学 A 才能学 B、先学 B 才能学 A」的学习路径就无法生成。'
            : '检测到依赖环，学习路径无法拓扑排序，请回到抽取结果核对前置关系。'}
        </p>
      </div>

      <div className="col-span-8 grid grid-cols-2 gap-4">
        {/* 剪枝数 */}
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-3.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-amber-800">
            <Scissors className="h-3.5 w-3.5" aria-hidden />
            因成环被剪除的边 pruned_count
          </div>
          <div className="mt-1.5 text-2xl font-semibold tabular-nums text-amber-700">{stats.pruned_count}</div>
          <p className="mt-1.5 text-xs leading-relaxed text-amber-900/90">
            「检出了 {stats.pruned_count} 条会成环的边并已剪除」—— 这比只写「环数 0」更有说服力：前者证明系统真的在逐边做环检测，而不只是恰好没出错。
          </p>
        </div>

        {/* 冲突边 */}
        <div className="rounded-xl border border-orange-200 bg-orange-50/50 p-3.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-orange-800">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
            结构-语义冲突边 conflict_count
          </div>
          <div className="mt-1.5 text-2xl font-semibold tabular-nums text-orange-700">{stats.conflict_count}</div>
          <p className="mt-1.5 text-xs leading-relaxed text-orange-900/90">
            语义上宣称的依赖与教材章节先后顺序矛盾时被登记（不静默丢弃）。冲突可见 = 歧义不掩盖，是评审可复核的原始数据。
          </p>
        </div>

        {/* 规模 */}
        <div className="col-span-2 rounded-xl border border-slate-200 bg-slate-50/60 p-3.5">
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-600">
            <GitBranch className="h-3.5 w-3.5" aria-hidden />
            图规模
          </div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-slate-700">
            <span>
              节点 <span className="font-semibold tabular-nums">{stats.node_count}</span>
            </span>
            <span>
              边 <span className="font-semibold tabular-nums">{stats.edge_count}</span>
              <span className="ml-1 text-xs text-slate-500">
                （硬 {stats.hard_edge_count} / 软 {stats.soft_edge_count}）
              </span>
            </span>
            {filtered && (
              <span className="text-xs text-slate-500">
                当前视图 {viewNodeCount} 节点 · {viewEdgeCount} 边（已应用筛选，统计值仍为后端全量）
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
