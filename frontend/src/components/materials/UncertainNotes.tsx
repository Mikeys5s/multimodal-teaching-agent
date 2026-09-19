import { AlertTriangle } from 'lucide-react'

import { SeverityBadge } from '@/components/ui/Badge'
import { UNCERTAIN_KIND_LABEL } from '@/lib/format'
import type { UncertainNote } from '@/lib/types'

/**
 * 存疑处列表（SPEC §4.4「存疑处」的定义必须实现 / F1.6 素材清单）。
 * 产品原则「显式不确定性」：把解析的短板主动标出来，不掩盖。
 */
export function UncertainNotes({ notes }: { notes: UncertainNote[] }) {
  if (notes.length === 0) {
    return <div className="text-xs text-slate-400">未检出存疑处。</div>
  }

  return (
    <ul className="space-y-2">
      {notes.map((note, index) => (
        <li
          key={`${note.kind}-${note.page}-${index}`}
          className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-medium text-amber-800">{UNCERTAIN_KIND_LABEL[note.kind] ?? note.kind}</span>
              <span className="text-amber-600">第 {note.page} 页</span>
              <SeverityBadge severity={note.severity} />
            </div>
            <div className="mt-0.5 text-xs text-slate-600">{note.message}</div>
          </div>
        </li>
      ))}
    </ul>
  )
}
