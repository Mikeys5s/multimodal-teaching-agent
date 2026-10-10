import { X } from 'lucide-react'

import { KnowledgePointDetail } from '@/components/graph/KnowledgePointDetail'

export interface KnowledgePointAsideProps {
  kpId: string | null
  onClose: () => void
}

/**
 * 桌面证据面板（/graph 画布右侧内嵌，≥lg 常驻）——
 * 选中节点时在画布旁直接展示证据，不再用弹层遮挡画布；
 * 内容与移动端底部抽屉共用（KnowledgePointDetail）。
 */
export function KnowledgePointAside({ kpId, onClose }: KnowledgePointAsideProps) {
  return (
    <aside className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-atlas-line bg-atlas-sheet">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-atlas-line bg-atlas-paper2 px-4 py-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-[0.13em] text-atlas-muted">
            SELECTED CONCEPT / 证据面板
          </div>
          <h3 className="mt-1 truncate text-sm font-semibold text-atlas-ink">
            {kpId ? '选中节点的证据' : '点选一个节点'}
          </h3>
        </div>
        {kpId && (
          <button
            type="button"
            onClick={onClose}
            aria-label="取消选中"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        {kpId ? (
          <KnowledgePointDetail kpId={kpId} />
        ) : (
          <p className="text-xs leading-relaxed text-atlas-muted">
            在左侧画布中点选任一知识点节点，这里会显示它的难度、前置、例题、误区与来源证据。
            也可用 Tab 遍历节点、Enter 打开。
          </p>
        )}
      </div>
    </aside>
  )
}
