import { Compass, Lightbulb, ListChecks } from 'lucide-react'

import { DifficultyBadge, Tag } from '@/components/ui/Badge'
import type { DiagnosisStuckAt, SseDiagnosis } from '@/lib/types'

/** 卡点来源证据：evidence_kp_id / evidence_misconception_id（都可能是 null） */
function StuckAt({ stuckAt }: { stuckAt: DiagnosisStuckAt }) {
  const evidence: { label: string; value: string }[] = []
  if (stuckAt.evidence_kp_id) evidence.push({ label: '知识点', value: stuckAt.evidence_kp_id })
  if (stuckAt.evidence_misconception_id)
    evidence.push({ label: '误区', value: stuckAt.evidence_misconception_id })

  return (
    <div className="space-y-1.5">
      <p className="text-xs leading-relaxed text-slate-700">{stuckAt.step}</p>
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[11px] text-slate-400">来源证据</span>
        {evidence.length > 0 ? (
          evidence.map((item) => (
            <Tag key={`${item.label}-${item.value}`}>
              {item.label} {item.value}
            </Tag>
          ))
        ) : (
          <span className="text-[11px] text-slate-400">本轮未定位到具体证据</span>
        )}
      </div>
    </div>
  )
}

/**
 * 「三件产出」面板 —— 对应 `diagnosis` 事件（SPEC R5）：
 * ① 涉及知识点（带 difficulty）② 卡在哪一步（+ 来源证据 id）③ 下一步建议练习。
 */
export function DiagnosisPanel({ diagnosis }: { diagnosis: SseDiagnosis }) {
  const { knowledge_points: kps, stuck_at: stuckAt, next_practice: nextPractice } = diagnosis

  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
      <div className="mb-2.5 flex items-center gap-2">
        <span className="text-xs font-semibold text-slate-700">本轮诊断 · 三件产出</span>
        <span className="font-mono text-[10px] text-slate-400">seq {diagnosis.seq}</span>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {/* ① 涉及知识点 */}
        <section className="rounded-lg border border-slate-200 bg-white p-2.5">
          <header className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-600">
            <Lightbulb className="h-3.5 w-3.5 text-amber-500" aria-hidden />
            ① 涉及知识点
          </header>
          {kps.length > 0 ? (
            <ul className="space-y-1.5">
              {kps.map((kp) => (
                <li key={kp.kp_id} className="space-y-1">
                  <div className="text-xs text-slate-800">{kp.name}</div>
                  <div className="flex flex-wrap items-center gap-1">
                    <DifficultyBadge difficulty={kp.difficulty} />
                    <Tag>{kp.kp_id}</Tag>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-slate-400">本轮未命中知识点</p>
          )}
        </section>

        {/* ② 卡在哪一步 */}
        <section className="rounded-lg border border-slate-200 bg-white p-2.5">
          <header className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-600">
            <Compass className="h-3.5 w-3.5 text-brand-600" aria-hidden />
            ② 卡在哪一步
          </header>
          {stuckAt ? (
            <StuckAt stuckAt={stuckAt} />
          ) : (
            <p className="text-[11px] text-slate-400">本轮没有定位到卡点</p>
          )}
        </section>

        {/* ③ 下一步建议练习 */}
        <section className="rounded-lg border border-slate-200 bg-white p-2.5">
          <header className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-600">
            <ListChecks className="h-3.5 w-3.5 text-emerald-600" aria-hidden />
            ③ 下一步建议练习
          </header>
          {nextPractice.length > 0 ? (
            <ul className="space-y-1.5">
              {nextPractice.map((item, index) => (
                <li key={`${item.kp_id}-${index}`} className="space-y-1">
                  <p className="text-xs leading-relaxed text-slate-700">{item.task}</p>
                  <Tag>{item.kp_id}</Tag>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-slate-400">本轮没有建议练习</p>
          )}
        </section>
      </div>
    </div>
  )
}
