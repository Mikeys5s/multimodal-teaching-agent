import { Route } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { GapAnalysisPanel } from '@/components/path/GapAnalysisPanel'
import { PathTimeline } from '@/components/path/PathTimeline'
import { TargetPicker } from '@/components/path/TargetPicker'
import { EmptyState } from '@/components/ui/Feedback'
import { api } from '@/lib/endpoints'
import { kpDisplayTitle } from '@/lib/kpTitle'
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

  /**
   * 深链：`/path?kp_id=xxx`（首页「从这看起」的第 1 个入口用它直达那一镜）。
   *
   * ⚠️ 两个坑，都踩过：
   *   1. **必须只消费一次** —— 否则用户用上方选择器换了目标后，这个 effect 会把他拽回深链那个点。
   *   2. **不要在 effect 里做「可取消」** —— 本应用开了 `<React.StrictMode>`，
   *      开发模式下 effect 会「执行 → 清理 → 再执行」。若在清理里把 cancelled 置真，
   *      第一次的异步结果会被丢弃，而第二次又因 ref 已消费直接 return ⇒ **深链永远不生效**。
   *      所以这里不取消：真正的卸载只会触发一次无害的 no-op setState。
   */
  const [searchParams] = useSearchParams()
  const deepLinkKpId = searchParams.get('kp_id')
  const deepLinkConsumed = useRef(false)

  useEffect(() => {
    if (deepLinkConsumed.current || !deepLinkKpId) return
    deepLinkConsumed.current = true
    void (async () => {
      // 路径本身只需要 id；拿名字只是为了界面上别出现 `kp_xxx`
      let name = deepLinkKpId
      try {
        name = kpDisplayTitle(await api.getKnowledgePoint(deepLinkKpId))
      } catch {
        // 详情取不到不影响路径渲染，先用 id 顶着
      }
      setTarget({ id: deepLinkKpId, name })
    })()
  }, [deepLinkKpId])

  const handleSelect = (kp: KnowledgePoint) => {
    setTarget({ id: kp.id, name: kpDisplayTitle(kp) })
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
          {/*
            key 绑定目标 id：换目标时重挂面板，清掉上一目标粘贴的误区证据。
            误区 id 属于旧知识点，带过去会让「最可能断层」按不相干的证据排序。
          */}
          <GapAnalysisPanel
            key={target.id}
            targetKpId={target.id}
            targetKpName={target.name}
          />
        </>
      ) : (
        <section className="xizhi-card">
          <EmptyState
            title="还没有选择目标知识点"
            description="在上方选一个知识点：系统会沿它的硬前置依赖反向遍历并做拓扑排序，给出「先学什么、后学什么」的有序路径，并回溯你可能卡住的更早环节。"
          />
          <div className="flex items-center justify-center gap-1.5 pb-10 text-xs text-slate-400">
            <Route className="h-3.5 w-3.5" aria-hidden />
            路径排序的每一步都会附上来自前置边的 reason —— 排序不是黑盒
          </div>
        </section>
      )}
    </div>
  )
}
