import { Route } from 'lucide-react'
import { useState } from 'react'

import { GapAnalysisPanel } from '@/components/path/GapAnalysisPanel'
import { PathTimeline } from '@/components/path/PathTimeline'
import { TargetPicker } from '@/components/path/TargetPicker'
import { EmptyState } from '@/components/ui/Feedback'
import type { KnowledgePoint } from '@/lib/types'

/** 只保留路径/回溯真正需要的字段，避免从路径时间线改选目标时还要回查完整知识点 */
interface PathTarget {
  id: string
  name: string
}

/**
 * 学习路径页（路由 /path，api-spec §8）。
 *
 * 覆盖 SPEC 的 F3.7 学习路径与 F3.8 卡点根因回溯：
 *   - `GET /api/learning-path?kp_id=`      → 拓扑有序步骤 + 每步 reason（排序可解释）
 *   - `GET /api/knowledge-points/{id}/gap-analysis` → 硬前置 / 最可能断层 / 补救建议
 *
 * 两个端点都以**单个知识点 id** 为入参，所以页面顺序是「先选目标 → 再看路径与回溯」。
 */
export default function PathPage() {
  const [target, setTarget] = useState<PathTarget | null>(null)

  const handleSelect = (kp: KnowledgePoint) => {
    setTarget({ id: kp.id, name: kp.name })
  }

  const handleRetarget = (kpId: string, kpName: string) => {
    setTarget({ id: kpId, name: kpName })
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <TargetPicker selectedId={target?.id ?? null} onSelect={handleSelect} />

      {target ? (
        <>
          <PathTimeline kpId={target.id} kpName={target.name} onRetarget={handleRetarget} />
          <GapAnalysisPanel targetKpId={target.id} targetKpName={target.name} />
        </>
      ) : (
        <section className="xizhi-card">
          <EmptyState
            title="还没有选择目标知识点"
            description="在上方选一个知识点：系统会沿它的硬前置依赖反向遍历并做拓扑排序，给出「先学什么、后学什么」的有序路径，并回溯你可能卡住的更早环节。"
          />
          <div className="flex items-center justify-center gap-1.5 pb-10 text-[11px] text-slate-400">
            <Route className="h-3.5 w-3.5" aria-hidden />
            路径排序的每一步都会附上来自前置边的 reason —— 排序不是黑盒
          </div>
        </section>
      )}
    </div>
  )
}
