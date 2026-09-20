import { RefreshCw, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { DifficultyBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import { DIFFICULTY_LABEL } from '@/lib/format'
import type { Difficulty, KnowledgePoint } from '@/lib/types'

const DIFFICULTY_OPTIONS: Difficulty[] = [1, 2, 3, 4, 5]

export interface TargetPickerProps {
  selectedId: string | null
  onSelect: (kp: KnowledgePoint) => void
}

/**
 * 目标知识点选择器。
 *
 * `/learning-path` 与 `/gap-analysis` 的入参都是**一个知识点的 id**（api-spec §4.4），
 * 不是整张图 —— 所以必须先让用户选定一个目标知识点，再往下拉路径与卡点回溯。
 * 过滤参数直接映射 `KnowledgePointQuery`（api-spec §4.2），不额外造字段。
 */
export function TargetPicker({ selectedId, onSelect }: TargetPickerProps) {
  const [draftKeyword, setDraftKeyword] = useState('')
  const [keyword, setKeyword] = useState('')
  const [difficulty, setDifficulty] = useState<Difficulty | ''>('')
  const [chapterId, setChapterId] = useState('')
  const [chapters, setChapters] = useState<{ id: string; title: string }[]>([])

  const filtered = Boolean(keyword || difficulty || chapterId)

  const listReq = useRequest(
    () =>
      api.listKnowledgePoints({
        page_size: 100,
        q: keyword || undefined,
        chapter_id: chapterId || undefined,
        difficulty_min: difficulty || undefined,
        difficulty_max: difficulty || undefined,
      }),
    [keyword, difficulty, chapterId],
  )

  const items = listReq.data?.items ?? []

  // 没有独立的章节列表接口，只能从已加载的知识点里累积去重出章节选项；
  // 「只增不减」是为了让选项在叠加过滤条件后不会突然消失。
  useEffect(() => {
    const data = listReq.data
    if (!data) return
    setChapters((prev) => {
      const seen = new Set(prev.map((item) => item.id))
      const next = [...prev]
      for (const kp of data.items) {
        if (!kp.chapter.id || seen.has(kp.chapter.id)) continue
        seen.add(kp.chapter.id)
        next.push({ id: kp.chapter.id, title: kp.chapter.title })
      }
      return next.length === prev.length ? prev : next
    })
  }, [listReq.data])

  const resetFilters = () => {
    setDraftKeyword('')
    setKeyword('')
    setDifficulty('')
    setChapterId('')
  }

  return (
    <section className="xizhi-card">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-sm font-semibold text-slate-800">目标知识点</h2>
          <span className="text-xs text-slate-400">
            {listReq.data ? `共 ${listReq.data.total} 个` : '加载中…'}
            {filtered && items.length > 0 && ` · 显示 ${items.length} 个`}
          </span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={listReq.loading}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void listReq.reload()}
        >
          刷新
        </Button>
      </header>

      <div className="space-y-3 p-4">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            setKeyword(draftKeyword.trim())
          }}
        >
          <label className="flex min-w-[220px] flex-1 flex-col gap-1">
            <span className="text-xs text-slate-500">关键词</span>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
                aria-hidden
              />
              <input
                value={draftKeyword}
                onChange={(event) => setDraftKeyword(event.target.value)}
                placeholder="按知识点名称搜索，回车确认"
                className="h-9 w-full rounded-lg border border-slate-300 bg-white pl-8 pr-3 text-sm text-slate-700 placeholder:text-slate-400 focus:xizhi-focus"
              />
            </div>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">难度</span>
            <select
              value={difficulty === '' ? '' : String(difficulty)}
              onChange={(event) => {
                const value = event.target.value
                setDifficulty(value === '' ? '' : (Number(value) as Difficulty))
              }}
              className="h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm text-slate-700"
            >
              <option value="">全部难度</option>
              {DIFFICULTY_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {value} · {DIFFICULTY_LABEL[value]}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">章节</span>
            <select
              value={chapterId}
              onChange={(event) => setChapterId(event.target.value)}
              className="h-9 min-w-[160px] rounded-lg border border-slate-300 bg-white px-2 text-sm text-slate-700"
            >
              <option value="">全部章节</option>
              {chapters.map((chapter) => (
                <option key={chapter.id} value={chapter.id}>
                  {chapter.title || chapter.id}
                </option>
              ))}
            </select>
          </label>

          <Button type="submit" size="md" loading={listReq.loading}>
            查询
          </Button>
          {filtered && (
            <button type="button" className="pb-2 text-xs text-brand-600 hover:underline" onClick={resetFilters}>
              清空筛选
            </button>
          )}
        </form>

        {listReq.error && <ErrorState message={listReq.error} onRetry={() => void listReq.reload()} />}

        {!listReq.error && listReq.loading && items.length === 0 && (
          <LoadingState label="正在加载知识点…" />
        )}

        {!listReq.error && !listReq.loading && items.length === 0 && (
          <EmptyState
            title={filtered ? '没有匹配的知识点' : '还没有知识点'}
            description={
              filtered
                ? '换个关键词或清空筛选条件再试。'
                : '先到「素材」页上传素材并触发知识点抽取，抽取完成后这里才会出现可选的目标知识点。'
            }
            action={
              !filtered ? (
                <Link
                  to="/materials"
                  className="inline-flex h-9 items-center rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
                >
                  去上传素材
                </Link>
              ) : undefined
            }
          />
        )}

        {items.length > 0 && (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {items.map((kp) => {
              const active = kp.id === selectedId
              return (
                <li key={kp.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(kp)}
                    aria-pressed={active}
                    className={[
                      'flex w-full items-start justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors',
                      active
                        ? 'border-brand-500 bg-brand-50/70'
                        : 'border-slate-200 bg-white hover:border-brand-300 hover:bg-slate-50',
                    ].join(' ')}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-700" title={kp.name}>
                        {kp.name}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-slate-400">
                        {kp.chapter.number} {kp.chapter.title}
                        {kp.section.title ? ` · ${kp.section.title}` : ''}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="text-[11px] text-slate-400">
                        前置 {kp.prerequisite_count} · 误区 {kp.misconception_count}
                      </span>
                      <DifficultyBadge difficulty={kp.difficulty} />
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}

        {items.length > 0 && (
          <p className="text-[11px] text-slate-400">
            选中一个知识点后，下方会按它的硬前置依赖输出拓扑有序的学习路径，并做卡点根因回溯。
          </p>
        )}
      </div>
    </section>
  )
}
