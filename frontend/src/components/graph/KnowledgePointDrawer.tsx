import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { KnowledgePointDetail } from '@/components/graph/KnowledgePointDetail'

export interface KnowledgePointDrawerProps {
  kpId: string
  onClose: () => void
}

/**
 * 知识点详情抽屉（移动端底部抽屉 / 窄屏弹层）。
 * 内容部分统一走 KnowledgePointDetail（与桌面右侧证据面板共用）。
 */
export function KnowledgePointDrawer({ kpId, onClose }: KnowledgePointDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  // 弹层行为契约：焦点进入、Escape 关闭、关闭后焦点返回、锁定背景滚动
  useEffect(() => {
    const prevOverflow = document.body.style.overflow
    const prevActive = document.activeElement instanceof HTMLElement ? document.activeElement : null
    document.body.style.overflow = 'hidden'
    panelRef.current?.querySelector<HTMLElement>('button')?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = prevOverflow
      document.removeEventListener('keydown', onKeyDown)
      prevActive?.focus()
    }
  }, [onClose])

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-stretch sm:justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />

      {/* 桌面窄屏：右侧抽屉；手机：底部抽屉（不遮关闭控件） */}
      <div
        ref={panelRef}
        className="relative flex max-h-[88vh] w-full flex-col rounded-t-2xl border-t border-atlas-line bg-atlas-sheet shadow-overlay sm:h-full sm:max-h-none sm:w-[360px] sm:rounded-none sm:border-l sm:border-t-0"
      >
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-atlas-line bg-atlas-paper2/60 px-5 py-3">
          <span className="text-xs font-semibold uppercase tracking-widest text-atlas-muted">
            选中节点证据
          </span>
          <button
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 sm:h-9 sm:w-9"
            onClick={onClose}
            aria-label="关闭详情"
          >
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          <KnowledgePointDetail kpId={kpId} />
        </div>
      </div>
    </div>
  )
}
