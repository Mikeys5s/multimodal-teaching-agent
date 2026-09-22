import { AlertTriangle, Lightbulb, Plus, RefreshCw, Target, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import type { GapAnalysis, GapPrerequisite } from '@/lib/types'

export interface GapAnalysisPanelProps {
  targetKpId: string
  targetKpName: string
}

/** 允许粘贴多个 id：空格 / 逗号 / 分号 / 换行都当分隔符 */
const EVIDENCE_SEPARATOR = /[\s,，;；]+/

function PrerequisiteItem({ item }: { item: GapPrerequisite }) {
  return (
    <li className="rounded-lg border border-slate-200 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-slate-700">{item.name}</span>
        <span className="shrink-0 rounded-full bg-brand-50 px-2 py-0.5 text-[11px] text-brand-700">
          第 {item.depth} 层前置
        </span>
      </div>
      {item.reason && <p className="mt-1 text-xs leading-relaxed text-slate-500">{item.reason}</p>}
      <div className="mt-1 font-mono text-[11px] text-slate-400">{item.kp_id}</div>
    </li>
  )
}

function AnalysisBody({ analysis }: { analysis: GapAnalysis }) {
  // 由近及远：第 1 层是直接前置，越往后越久远
  const prerequisites = [...analysis.hard_prerequisites].sort((a, b) => a.depth - b.depth)
  const { likely_gap: likelyGap } = analysis

  return (
    <div className="space-y-4">
      {/* 目标 */}
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2">
        <Target className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
        <span className="text-xs text-slate-500">回溯目标</span>
        <span className="text-sm font-medium text-slate-700">{analysis.target_kp.name}</span>
        <span className="font-mono text-[11px] text-slate-400">{analysis.target_kp.kp_id}</span>
      </div>

      {/* 必须补的前置 */}
      <section>
        <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs font-medium text-slate-600">
          <span>必须补的硬前置</span>
          <span className="text-slate-400">（{prerequisites.length}）</span>
          <span className="text-slate-400">沿 hard 边反向可达，由近及远</span>
        </div>
        <p className="mb-2 text-[11px] leading-relaxed text-slate-400">
          硬前置 = 不会就学不动（约束先后）；软前置 = 有帮助、非必需。只有硬前置会被用在这个回溯里。
        </p>
        {prerequisites.length === 0 ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs leading-relaxed text-amber-900">
            <p className="font-medium">未检出硬前置 —— 但这不等于它可以直接学起。</p>
            <p className="mt-1 text-amber-800">
              这个回溯只沿「hard 边」走。如果当前图里还没有 hard 边（依赖边全是 AI 预抽取的软前置、待人工确认），
              这里返回 0 只说明「无法判定」，不说明它是起点。
              界面上别处若显示它有前置（软前置），两者并不矛盾。
            </p>
          </div>
        ) : (
          <ul className="space-y-2">
            {prerequisites.map((item) => (
              <PrerequisiteItem key={item.kp_id} item={item} />
            ))}
          </ul>
        )}
      </section>

      {/* 最可能的断层 */}
      <section>
        <div className="mb-2 text-xs font-medium text-slate-600">最可能的断层</div>
        {likelyGap ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" aria-hidden />
              <span className="text-sm font-medium text-amber-900">{likelyGap.name}</span>
              <Badge color="#f59e0b">根因候选</Badge>
            </div>
            {likelyGap.evidence && (
              <p className="mt-1.5 text-xs leading-relaxed text-amber-800">{likelyGap.evidence}</p>
            )}
            <div className="mt-1.5 text-[11px] text-amber-700/80">
              溯源：素材 <span className="font-mono">{likelyGap.source.material_id}</span> · 第{' '}
              {likelyGap.source.page} 页
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2 text-xs text-slate-500">
            没有识别出明显的断层 —— 该知识点沿硬前置反向可达的关系里，没有哪一条显著地比其它更可疑。
          </div>
        )}
      </section>

      {/* 建议 */}
      {analysis.suggestion && (
        <section className="rounded-lg border border-brand-100 bg-brand-50/60 p-3">
          <div className="mb-1 flex items-center gap-1.5 text-xs font-medium text-brand-700">
            <Lightbulb className="h-3.5 w-3.5" aria-hidden />
            补救建议
          </div>
          <p className="text-xs leading-relaxed text-brand-900">{analysis.suggestion}</p>
        </section>
      )}
    </div>
  )
}

/**
 * 卡点根因回溯面板（F3.8 / api-spec §4.4）。
 *
 * `student_evidence` 是**可重复**查询参数，传的是 `kp_misconceptions.id`：
 * `?student_evidence=mis_a&student_evidence=mis_b`。
 * 关键契约：**无效 id 会被后端忽略而不是报错**（只影响「最可能断层」的排序精度），
 * 因此这里不预先校验 id 的合法性 —— 用户粘错一个 id 不该让整次回溯失败。
 *
 * 项目里没有「学生本轮误区列表」接口，所以这里用可增删的输入框由用户粘贴 id。
 */
export function GapAnalysisPanel({ targetKpId, targetKpName }: GapAnalysisPanelProps) {
  const [evidenceIds, setEvidenceIds] = useState<string[]>([])
  const [draft, setDraft] = useState('')

  const gapReq = useRequest(() => api.getGapAnalysis(targetKpId, evidenceIds), [targetKpId], {
    immediate: false,
  })
  const reload = gapReq.reload

  // 换目标知识点时自动按「不带误区证据」跑一次；证据变更由用户点「重新分析」触发
  useEffect(() => {
    void reload()
  }, [reload])

  const addEvidence = (raw: string) => {
    const parts = raw.split(EVIDENCE_SEPARATOR).filter(Boolean)
    if (parts.length === 0) return
    setEvidenceIds((prev) => {
      const next = [...prev]
      for (const part of parts) if (!next.includes(part)) next.push(part)
      return next
    })
    setDraft('')
  }

  const analysis = gapReq.data

  return (
    <section className="xizhi-card">
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-3">
            <h2 className="text-sm font-semibold text-slate-800">卡点根因回溯</h2>
            <span className="truncate text-xs text-slate-400" title={targetKpName}>
              目标：{targetKpName}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            沿硬前置边反向可达，找出「不是这一题不会，而是更早的知识点没吃透」的那一环。
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={gapReq.loading}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void reload()}
        >
          重新分析
        </Button>
      </header>

      <div className="space-y-4 p-4">
        {/* 误区证据输入 */}
        <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
          <div className="mb-2 text-xs font-medium text-slate-600">学生误区证据（kp_misconceptions.id）</div>
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              addEvidence(draft)
            }}
          >
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="粘贴误区 id，可一次多个，用空格 / 逗号分隔"
              className="h-8 flex-1 rounded-lg border border-slate-300 bg-white px-2.5 font-mono text-xs text-slate-700 placeholder:font-sans placeholder:text-slate-400 focus:xizhi-focus"
            />
            <Button type="submit" variant="secondary" size="sm" icon={<Plus className="h-3.5 w-3.5" />} disabled={!draft.trim()}>
              添加
            </Button>
          </form>

          {evidenceIds.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              {evidenceIds.map((id) => (
                <span
                  key={id}
                  className="inline-flex items-center gap-1 rounded-md bg-white px-2 py-0.5 font-mono text-[11px] text-slate-600 ring-1 ring-slate-200"
                >
                  {id}
                  <button
                    type="button"
                    className="text-slate-400 hover:text-red-500"
                    aria-label={`移除 ${id}`}
                    onClick={() => setEvidenceIds((prev) => prev.filter((item) => item !== id))}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              <button
                type="button"
                className="ml-1 text-[11px] text-slate-500 hover:text-brand-600 hover:underline"
                onClick={() => setEvidenceIds([])}
              >
                清空
              </button>
            </div>
          )}

          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
            无效 id 会被后端<b className="font-medium text-slate-500">忽略而不是报错</b>
            ，只影响「最可能断层」的排序精度，不影响本次请求成功；所以这里不做格式校验，粘错了也不会让回溯失败。
          </p>
        </div>

        {gapReq.error && (
          <div>
            <ErrorState message={gapReq.error} onRetry={() => void reload()} />
            <p className="mt-3 text-center text-xs text-slate-400">
              若为首次运行，请确认后端已启动（可访问 /api/health 自检），再点「重试」。
            </p>
          </div>
        )}

        {!gapReq.error && gapReq.loading && !analysis && (
          <LoadingState label="正在回溯硬前置与断层排序…" />
        )}

        {!gapReq.error && !gapReq.loading && !analysis && (
          <EmptyState
            title="没有拿到回溯结果"
            description="换一个目标知识点，或点右上角「重新分析」再试一次。"
          />
        )}

        {!gapReq.error && analysis && <AnalysisBody analysis={analysis} />}
      </div>
    </section>
  )
}
