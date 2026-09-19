import { FileSearch, ShieldAlert } from 'lucide-react'

import { Tag } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Feedback'
import type { SseRetrieved } from '@/lib/types'

/**
 * 溯源卡片 —— 对应 `retrieved` 事件。
 *
 * 契约要求它**先于任何 `delta`** 到达（api-spec §5.2），所以本卡片在界面上位于
 * 回答正文之前，是「先检索材料、再组织回答」这条链路在界面上的可见证据。
 */
export function TraceCard({ retrieved, pending }: { retrieved: SseRetrieved | null; pending: boolean }) {
  if (!retrieved) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs text-slate-500">
        <Spinner className="h-3.5 w-3.5" />
        第 1 步 · 正在检索材料（先定范围，再作答）…
      </div>
    )
  }

  const outOfScope = retrieved.is_out_of_scope
  const pendingTail = pending && retrieved.kp_ids.length === 0 && retrieved.block_ids.length === 0

  return (
    <div
      className={[
        'rounded-lg border px-3 py-2.5 text-xs',
        outOfScope ? 'border-red-200 bg-red-50/70' : 'border-brand-100 bg-brand-50/50',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-center gap-2">
        {outOfScope ? (
          <ShieldAlert className="h-3.5 w-3.5 shrink-0 text-red-500" aria-hidden />
        ) : (
          <FileSearch className="h-3.5 w-3.5 shrink-0 text-brand-600" aria-hidden />
        )}
        <span className="font-medium text-slate-700">第 1 步 · 检索材料</span>
        <span className="text-slate-400">
          命中 {retrieved.kp_ids.length} 个知识点 / {retrieved.block_ids.length} 个原文块
        </span>
        <span className="font-mono text-[10px] text-slate-400">seq {retrieved.seq}</span>
        {pendingTail && <Spinner className="h-3 w-3" />}
      </div>

      {outOfScope && (
        <div className="mt-1.5 rounded-md bg-red-100/80 px-2 py-1.5 font-medium text-red-700">
          本次提问超出材料范围，将拒答 —— 不会使用材料以外的知识作答。
        </div>
      )}

      <div className="mt-2 space-y-1">
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-slate-500">知识点</span>
          {retrieved.kp_ids.length > 0 ? (
            retrieved.kp_ids.map((id) => <Tag key={id}>{id}</Tag>)
          ) : (
            <span className="text-slate-400">未命中</span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-slate-500">原文块</span>
          {retrieved.block_ids.length > 0 ? (
            retrieved.block_ids.map((id) => <Tag key={id}>{id}</Tag>)
          ) : (
            <span className="text-slate-400">未命中</span>
          )}
        </div>
      </div>
    </div>
  )
}
