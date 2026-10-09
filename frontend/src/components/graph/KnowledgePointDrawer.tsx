import { AlertTriangle, BookOpen, GitBranch, Layers, Link2, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

import { DifficultyBadge } from '@/components/ui/Badge'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import { formatPercent, formatScore } from '@/lib/format'
import { dupNotice, kpDisplayTitle, kpTitleAttr } from '@/lib/kpTitle'
import type { Example, KpType, Misconception, Prerequisite, RelationType } from '@/lib/types'

const RELATION_LABEL: Record<RelationType, string> = {
  hard: '硬前置（不会就不能学）',
  soft: '软前置（有帮助，非必需）',
}

/**
 * 知识点类型的显示名。
 *
 * ⚠️ 这个字段（`kp_type`）是 `GET /api/knowledge-points/{id}` 契约里的**必填**字段，
 * 而此前整个前端**一处都没渲染**（9/21 交付物审计发现）——
 * 数据一直在手上却没用上，属于「契约承诺了但界面不给」。
 */
const KP_TYPE_LABEL: Record<KpType, string> = {
  concept: '概念',
  method: '方法',
  skill: '技能',
  principle: '原理',
  protocol: '协议',
  other: '其他',
}

const MISCONCEPTION_SOURCE_LABEL: Record<string, string> = {
  human: '人工标注',
  material: '材料原文',
  // 后端派生内容用的就是 llm_inferred —— 界面上说清是"派生"，不谎称人工
  llm_inferred: '由原文派生',
  ai: 'AI 归纳',
}

/** 例题来源徽章的文案与样式。 */
const EXAMPLE_SOURCE_BADGE: Record<string, { label: string; className: string }> = {
  human: { label: '人工精选', className: 'bg-success-soft text-success' },
  derived: { label: '由原文派生', className: 'bg-slate-100 text-slate-500' },
}

function SectionHeading({
  icon,
  title,
  count,
}: {
  icon: ReactNode
  title: string
  count: number
}) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-600">
      {icon}
      {title}
      <span className="text-slate-400">（{count}）</span>
    </div>
  )
}

function PrerequisiteItem({ item }: { item: Prerequisite }) {
  const hard = item.relation_type === 'hard'
  return (
    <li className="rounded-lg border border-slate-200 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-slate-700">{item.name}</span>
        <span
          className={[
            'shrink-0 rounded-full px-2 py-0.5 text-xs',
            hard ? 'bg-brand-50 text-brand-700' : 'bg-slate-100 text-slate-500',
          ].join(' ')}
        >
          {RELATION_LABEL[item.relation_type]}
        </span>
      </div>
      {item.reason && <p className="mt-1 text-xs leading-relaxed text-slate-500">{item.reason}</p>}
      <div className="mt-1 text-xs text-slate-400">置信度 {formatScore(item.confidence)}</div>
    </li>
  )
}

function ExampleItem({ item, index }: { item: Example; index: number }) {
  return (
    <li className="rounded-lg border border-slate-200 p-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="text-xs font-medium text-slate-400">例 {index + 1}</span>
        <DifficultyBadge difficulty={item.difficulty} />
        {item.source_page != null && item.source_page > 0 && (
          <span className="text-xs text-slate-400">第 {item.source_page} 页</span>
        )}
        {(() => {
          const badge = EXAMPLE_SOURCE_BADGE[item.source ?? 'human']
          if (!badge) return null
          return (
            <span className={`rounded-full px-1.5 py-0.5 text-xs ${badge.className}`}>
              {badge.label}
            </span>
          )
        })()}
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{item.stem_md}</p>
      {item.options_json && item.options_json.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {item.options_json.map((option, optionIndex) => (
            <li key={optionIndex} className="text-xs text-slate-600">
              {option}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 rounded-md bg-success-soft px-2 py-1.5">
        <div className="text-xs font-medium text-success">答案</div>
        <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{item.answer_md}</p>
      </div>
      {item.analysis_md && (
        <div className="mt-1.5 rounded-md bg-slate-50 px-2 py-1.5">
          <div className="text-xs font-medium text-slate-500">解析</div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-slate-600">{item.analysis_md}</p>
        </div>
      )}
    </li>
  )
}

function MisconceptionItem({ item }: { item: Misconception }) {
  return (
    <li className="rounded-lg border border-warning-line bg-warning-soft p-2.5">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-warning">{item.description}</span>
        <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-xs text-warning">
          {MISCONCEPTION_SOURCE_LABEL[item.source] ?? item.source}
        </span>
      </div>
      {item.cause && (
        <p className="mt-1 text-xs leading-relaxed text-warning">
          <span className="font-medium">成因：</span>
          {item.cause}
        </p>
      )}
      {item.remedy && (
        <p className="mt-0.5 text-xs leading-relaxed text-warning">
          <span className="font-medium">纠正：</span>
          {item.remedy}
        </p>
      )}
      <div className="mt-1 text-xs text-warning">置信度 {formatScore(item.confidence)}</div>
    </li>
  )
}

export interface KnowledgePointDrawerProps {
  kpId: string
  onClose: () => void
}

/** 知识点详情抽屉：数据源 GET /api/knowledge-points/{id}（api-spec §4.3） */
export function KnowledgePointDrawer({ kpId, onClose }: KnowledgePointDrawerProps) {
  const detailReq = useRequest(() => api.getKnowledgePoint(kpId), [kpId])
  const detail = detailReq.data
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
  /**
   * 决赛任务 1「重复组前端呈现」。
   * `null` = 后端未给字段 / 该点是独立知识点（组内只有它自己）→ 界面**不出现任何提示**，
   * 避免给独立点也挂一句「已合并显示」。
   */
  const dupHint = detail ? dupNotice(detail) : null

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center sm:items-stretch sm:justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />

      {/* 桌面：右侧 360px 抽屉；手机：底部抽屉（不遮关闭控件） */}
      <div
        ref={panelRef}
        className="relative flex max-h-[88vh] w-full flex-col rounded-t-2xl border-t border-slate-200 bg-white shadow-overlay sm:h-full sm:max-h-none sm:w-[360px] sm:rounded-none sm:border-l sm:border-t-0"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            {/*
              决赛任务 2「可读标题显示」：优先用后端 `display_title`，没有就回落 `name`。
              拿到可读标题时，把**原始句片段**收进 `title` 属性 —— 悬停可见，溯源不丢。
            */}
            <h2
              className="truncate text-sm font-semibold text-slate-800"
              title={detail ? kpTitleAttr(detail) : undefined}
            >
              {detail ? kpDisplayTitle(detail) : '知识点详情'}
            </h2>
            {detail && (
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-400">
                <DifficultyBadge difficulty={detail.difficulty} />
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                  {KP_TYPE_LABEL[detail.kp_type] ?? detail.kp_type}
                </span>
                <span>
                  {detail.chapter.number} {detail.chapter.title}
                  {detail.section.title ? ` · ${detail.section.title}` : ''}
                </span>
              </div>
            )}
          </div>
          <button
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 sm:h-9 sm:w-9"
            onClick={onClose}
            aria-label="关闭详情"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          {detailReq.loading && !detail && <LoadingState label="正在加载知识点详情…" />}

          {detailReq.error && (
            <ErrorState message={detailReq.error} onRetry={() => void detailReq.reload()} />
          )}

          {detail && (
            <div className="space-y-5">
              {/*
                决赛任务 1：重复组提示。
                ⚠️ 措辞由 lib/kpTitle.ts 的 dupNotice() 统一产出 —— **只标注、不去重**，
                   任何地方都不得出现「已去重」。
              */}
              {dupHint && (
                <div className="flex items-start gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                  <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
                  <div className="min-w-0">
                    <p>{dupHint}</p>
                    {detail.is_duplicate && detail.duplicate_of && (
                      <p className="mt-1 font-mono text-xs text-slate-400">
                        代表点：{detail.duplicate_of}
                      </p>
                    )}
                  </div>
                </div>
              )}

              {detail.needs_review && (
                <div className="flex items-start gap-2 rounded-lg border border-warning-line bg-warning-soft px-3 py-2 text-xs text-warning">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                  <span>该知识点被标记为「待复核」，前置关系或字段存在不确定处，建议人工确认。</span>
                </div>
              )}

              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{detail.summary_md}</p>

              {detail.difficulty_reason && (
                <div className="text-xs leading-relaxed text-slate-500">
                  <span className="font-medium text-slate-600">难度依据：</span>
                  {detail.difficulty_reason}
                </div>
              )}

              {/* 前置 */}
              <section>
                <SectionHeading
                  icon={<GitBranch className="h-3.5 w-3.5" aria-hidden />}
                  title="前置依赖"
                  count={detail.prerequisites.length}
                />
                {detail.prerequisites.length === 0 ? (
                  <p className="text-xs text-slate-400">没有前置 —— 这是依赖图的起点，可以直接从这里学起。</p>
                ) : (
                  <ul className="space-y-2">
                    {detail.prerequisites.map((item) => (
                      <PrerequisiteItem key={item.kp_id} item={item} />
                    ))}
                  </ul>
                )}
              </section>

              {/* 典型例题 */}
              <section>
                <SectionHeading
                  icon={<BookOpen className="h-3.5 w-3.5" aria-hidden />}
                  title="典型例题"
                  count={detail.examples.length}
                />
                {detail.examples.length === 0 ? (
                  <p className="text-xs text-slate-400">暂无例题。</p>
                ) : (
                  <ul className="space-y-2">
                    {detail.examples.map((item, index) => (
                      <ExampleItem key={item.id} item={item} index={index} />
                    ))}
                  </ul>
                )}
              </section>

              {/* 常见误区 */}
              <section>
                <SectionHeading
                  icon={<AlertTriangle className="h-3.5 w-3.5" aria-hidden />}
                  title="常见误区"
                  count={detail.misconceptions.length}
                />
                {detail.misconceptions.length === 0 ? (
                  <p className="text-xs text-slate-400">暂无误区记录。</p>
                ) : (
                  <ul className="space-y-2">
                    {detail.misconceptions.map((item) => (
                      <MisconceptionItem key={item.id} item={item} />
                    ))}
                  </ul>
                )}
              </section>

              {/* 溯源 */}
              <section className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-600">
                  <Link2 className="h-3.5 w-3.5" aria-hidden />
                  原文溯源
                </div>
                <div className="text-xs text-slate-500">
                  {detail.source.material_name} · 第 {detail.source.page} 页
                </div>
                {detail.source.quote && (
                  <p className="mt-1.5 whitespace-pre-wrap border-l-2 border-slate-300 pl-2 text-xs leading-relaxed text-slate-600">
                    {detail.source.quote}
                  </p>
                )}
                <div className="mt-1.5 text-xs text-slate-400">
                  抽取置信度 {formatPercent(detail.confidence)} · 例题 {detail.example_count} · 前置{' '}
                  {detail.prerequisite_count} · 误区 {detail.misconception_count}
                </div>
              </section>
            </div>
          )}

          {!detail && !detailReq.loading && !detailReq.error && (
            <EmptyState title="没有找到该知识点的详情" description="它可能已被重新抽取替换，请刷新图谱。" />
          )}
        </div>
      </div>
    </div>
  )
}
