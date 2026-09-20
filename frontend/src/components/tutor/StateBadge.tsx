import { ArrowDownCircle, ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import type { SseState } from '@/lib/types'

import { MAX_HINT_LEVEL, SOCRATIC_STATE_COLOR, SOCRATIC_STATE_LABEL, TURN_TYPE_LABEL } from './labels'

/**
 * `state` 事件徽标 —— 把「本轮走的是哪一步、提示到几级」直接摊开给用户看。
 * `turn_type === 'explain'` 即后端兜底降级（prompt-contracts P7），必须显式告知。
 */
export function StateBadge({ state }: { state: SseState }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge color={SOCRATIC_STATE_COLOR[state.state]} dot>
        {SOCRATIC_STATE_LABEL[state.state]}
      </Badge>
      <span className="font-mono text-[10px] text-slate-400">{state.state}</span>
      <span className="text-xs text-slate-500">动作：{TURN_TYPE_LABEL[state.turn_type]}</span>
      <span className="text-xs text-slate-400">
        提示级别 {state.hint_level} / {MAX_HINT_LEVEL}
      </span>

      {state.turn_type === 'explain' && (
        <span className="inline-flex items-center gap-1 rounded-md bg-amber-100/80 px-2 py-0.5 text-xs font-medium text-amber-800">
          <ArrowDownCircle className="h-3 w-3" aria-hidden />
          连续答不上来，已降级为直接讲解
        </span>
      )}
      {state.turn_type === 'refuse' && (
        <span className="inline-flex items-center gap-1 rounded-md bg-red-100/80 px-2 py-0.5 text-xs font-medium text-red-700">
          <ShieldAlert className="h-3 w-3" aria-hidden />
          检索不到材料依据，走拒答模板
        </span>
      )}
    </div>
  )
}
