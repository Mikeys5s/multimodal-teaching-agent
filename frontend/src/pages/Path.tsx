import { Route } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { GapAnalysisPanel } from '@/components/path/GapAnalysisPanel'
import { PathHero } from '@/components/path/PathHero'
import { PathTimeline } from '@/components/path/PathTimeline'
import { TargetFilters, TargetIndex, useTargetPickerState } from '@/components/path/TargetPicker'
import { EmptyState } from '@/components/ui/Feedback'
import { api } from '@/lib/endpoints'
import { formatChapterRef } from '@/lib/format'
import { kpDisplayTitle } from '@/lib/kpTitle'
import type { KnowledgePoint } from '@/lib/types'

/** 只保留路径/回溯真正需要的字段，避免从路径时间线改选目标时还要回查完整知识点 */
interface PathTarget {
  id: string
  name: string
  /** 章节展示用（选择器列表自带；深链时从详情接口补） */
  chapterLabel?: string
}

/**
 * 学习路径页（路由 /path，api-spec §8）。
 *
 * 覆盖 SPEC 的 F3.7 学习路径与 F3.8 卡点根因回溯：
 *   - `GET /api/learning-path?kp_id=`      → 拓扑有序步骤 + 每步 reason（排序可解释）
 *   - `GET /api/knowledge-points/{id}/gap-analysis` → 硬前置 / 最可能断层 / 补救建议
 *
 * 两个端点都以**单个知识点 id** 为入参，所以页面顺序是「先选目标 → 再看路径与回溯」。
 * 构图（Learning Atlas v2）：页头 → 目标面板（深蓝）→ 筛选行 → INDEX 侧栏 + 步骤时间线。
 */
export default function PathPage() {
  const [target, setTarget] = useState<PathTarget | null>(null)
  const picker = useTargetPickerState()

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
      // 路径本身只需要 id；拿名字与章节只是为了界面上别出现 `kp_xxx`。
      // ⚠️ display_title 只在 learning-path 响应里带（详情接口没有这个字段）——
      //    hero 标题用路径末步（即目标点）的 display_title，其次详情 name，最后回落 id。
      let name = deepLinkKpId
      let chapterLabel: string | undefined
      try {
        const [steps, detail] = await Promise.allSettled([
          api.getLearningPath(deepLinkKpId),
          api.getKnowledgePoint(deepLinkKpId),
        ])
        if (detail.status === 'fulfilled') {
          const ref = formatChapterRef(detail.value.chapter)
          chapterLabel = ref || undefined
          name = detail.value.name
        }
        if (steps.status === 'fulfilled' && steps.value.length > 0) {
          const last = steps.value[steps.value.length - 1]
          name = kpDisplayTitle(last)
        }
      } catch {
        // 详情/路径取不到不影响渲染，先用 id 顶着
      }
      setTarget({ id: deepLinkKpId, name, chapterLabel })
    })()
  }, [deepLinkKpId])

  const handleSelect = (kp: KnowledgePoint) => {
    const ref = formatChapterRef(kp.chapter)
    setTarget({ id: kp.id, name: kpDisplayTitle(kp), chapterLabel: ref || undefined })
  }

  const handleRetarget = (kpId: string, kpName: string) => {
    setTarget((prev) => ({ id: kpId, name: kpName, chapterLabel: prev?.id === kpId ? prev.chapterLabel : undefined }))
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      {/* 页头：编辑式标题（刷新在各面板内，避免重复主操作） */}
      <div className="min-w-0">
        <div className="atlas-eyebrow">
          <span className="idx">04</span> LEARNING ROUTE / PREREQUISITES
        </div>
        <h2 className="atlas-h1 mt-2">先后顺序，也要有证据。</h2>
        <p className="mt-2 max-w-[560px] text-[13px] leading-relaxed text-atlas-muted">
          选择目标知识点后，沿着已确认的硬前置关系向前追溯。
        </p>
      </div>

      {target && <PathHero targetName={target.name} chapterLabel={target.chapterLabel} />}

      {/* 筛选行 */}
      <TargetFilters state={picker} />

      {/* INDEX 侧栏 + 步骤时间线 */}
      <section className="atlas-sheet-panel grid min-h-[420px] overflow-hidden md:grid-cols-[230px_minmax(0,1fr)]">
        <div className="border-b border-[#d7d0c4] bg-atlas-paper2/60 md:max-h-none md:border-b-0 md:border-r">
          <TargetIndex state={picker} selectedId={target?.id ?? null} onSelect={handleSelect} />
        </div>

        {target ? (
          <PathTimeline kpId={target.id} kpName={target.name} onRetarget={handleRetarget} />
        ) : (
          <div className="flex flex-col">
            <EmptyState
              title="还没有选择目标知识点"
              description="在左侧选一个知识点：系统会沿它的硬前置依赖反向遍历并做拓扑排序，给出「先学什么、后学什么」的有序路径，并回溯你可能卡住的更早环节。"
            />
            <div className="flex items-center justify-center gap-1.5 pb-10 text-xs text-atlas-muted">
              <Route className="h-3.5 w-3.5" aria-hidden />
              路径排序的每一步都会标注可核对的先后关系 —— 排序不是黑盒
            </div>
          </div>
        )}
      </section>

      {target && (
        /*
          key 绑定目标 id：换目标时重挂面板，清掉上一目标粘贴的误区证据。
          误区 id 属于旧知识点，带过去会让「最可能断层」按不相干的证据排序。
        */
        <GapAnalysisPanel
          key={target.id}
          targetKpId={target.id}
          targetKpName={target.name}
        />
      )}
    </div>
  )
}
