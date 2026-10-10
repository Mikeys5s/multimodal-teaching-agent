import { RefreshCw, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { DifficultyBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import { DIFFICULTY_LABEL } from '@/lib/format'
import { kpDisplayTitle, kpTitleAttr } from '@/lib/kpTitle'
import type { Difficulty, KnowledgePoint } from '@/lib/types'

const DIFFICULTY_OPTIONS: Difficulty[] = [1, 2, 3, 4, 5]

export interface TargetPickerState {
  items: KnowledgePoint[]
  total: number | null
  loading: boolean
  error: string | null
  filtered: boolean
  reload: () => void
  setDraftKeyword: (value: string) => void
  draftKeyword: string
  submitKeyword: () => void
  resetFilters: () => void
  difficulty: Difficulty | ''
  setDifficulty: (value: Difficulty | '') => void
  chapterId: string
  setChapterId: (value: string) => void
  chapters: { id: string; title: string }[]
}

/**
 * 目标知识点的查询状态（`/learning-path` 与 `/gap-analysis` 的入参都是一个知识点 id，
 * api-spec §4.4 —— 必须先选定目标再拉路径与卡点回溯）。
 * 过滤参数直接映射 `KnowledgePointQuery`（api-spec §4.2），不额外造字段。
 */
export function useTargetPickerState(): TargetPickerState {
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

  return {
    items,
    total: listReq.data?.total ?? null,
    loading: listReq.loading,
    error: listReq.error,
    filtered,
    reload: () => void listReq.reload(),
    setDraftKeyword,
    draftKeyword,
    submitKeyword: () => setKeyword(draftKeyword.trim()),
    resetFilters,
    difficulty,
    setDifficulty,
    chapterId,
    setChapterId,
    chapters,
  }
}

/** 筛选行：搜索 + 难度/章节胶囊 + 查询（胶囊式，与图谱筛选行同构） */
export function TargetFilters({ state }: { state: TargetPickerState }) {
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault()
        state.submitKeyword()
      }}
    >
      <label className="relative w-full min-w-0 sm:w-auto sm:flex-1 sm:min-w-[240px]">
        <span className="sr-only">按知识点名称搜索</span>
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
          aria-hidden
        />
        <input
          value={state.draftKeyword}
          onChange={(event) => state.setDraftKeyword(event.target.value)}
          placeholder="按知识点名称搜索，回车确认"
          className="h-11 w-full rounded-lg border border-[#d5cfc3] bg-atlas-sheet pl-9 pr-3 text-sm text-slate-700 placeholder:text-slate-400 focus:xizhi-focus sm:h-10"
        />
      </label>

      <label className="inline-flex items-center gap-1.5 rounded-full border border-[#d2ccbf] bg-atlas-sheet px-3 py-2 text-xs text-[#536073]">
        难度
        <select
          value={state.difficulty === '' ? '' : String(state.difficulty)}
          onChange={(event) => {
            const value = event.target.value
            state.setDifficulty(value === '' ? '' : (Number(value) as Difficulty))
          }}
          aria-label="按难度筛选"
          className="bg-transparent text-xs text-atlas-ink outline-none"
        >
          <option value="">全部难度</option>
          {DIFFICULTY_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {value} · {DIFFICULTY_LABEL[value]}
            </option>
          ))}
        </select>
      </label>

      <label className="inline-flex items-center gap-1.5 rounded-full border border-[#d2ccbf] bg-atlas-sheet px-3 py-2 text-xs text-[#536073]">
        章节
        <select
          value={state.chapterId}
          onChange={(event) => state.setChapterId(event.target.value)}
          aria-label="按章节筛选"
          className="max-w-[160px] bg-transparent text-xs text-atlas-ink outline-none"
        >
          <option value="">全部章节</option>
          {state.chapters.map((chapter) => (
            <option key={chapter.id} value={chapter.id}>
              {chapter.title || chapter.id}
            </option>
          ))}
        </select>
      </label>

      <Button type="submit" loading={state.loading}>
        查询
      </Button>
      {state.filtered && (
        <button type="button" className="min-h-11 text-xs text-brand-600 hover:underline sm:min-h-0" onClick={state.resetFilters}>
          清空筛选
        </button>
      )}

      <span className="ml-auto hidden text-xs text-atlas-muted md:inline">
        {state.total !== null ? `共 ${state.total} 个` : '加载中…'}
        {state.filtered && state.items.length > 0 && ` · 显示 ${state.items.length} 个`}
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        loading={state.loading}
        icon={<RefreshCw className="h-3.5 w-3.5" />}
        onClick={state.reload}
      >
        刷新
      </Button>
    </form>
  )
}

/** INDEX 侧栏：可点的目标清单（path-board 左栏） */
export function TargetIndex({
  state,
  selectedId,
  onSelect,
}: {
  state: TargetPickerState
  selectedId: string | null
  onSelect: (kp: KnowledgePoint) => void
}) {
  const { items, loading, error, filtered, reload } = state

  return (
    <div className="flex min-h-0 flex-col">
      <div className="border-b border-[#d7d0c4] px-4 pb-3 pt-4">
        <div className="atlas-eyebrow !text-[10px]">
          <span className="idx">INDEX</span> TARGET LIST
        </div>
        <h3 className="mt-2 text-sm font-semibold text-atlas-ink">选择一个目标</h3>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {error && <ErrorState message={error} onRetry={reload} />}

        {!error && loading && items.length === 0 && <LoadingState label="正在加载知识点…" />}

        {!error && !loading && items.length === 0 && (
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

        <ul className="space-y-0.5">
          {items.map((kp) => {
            const active = kp.id === selectedId
            return (
              <li key={kp.id}>
                <button
                  type="button"
                  onClick={() => onSelect(kp)}
                  aria-pressed={active}
                  className={[
                    'w-full rounded-lg px-2.5 py-2 text-left transition-colors duration-120',
                    active
                      ? 'bg-[#dce5f4] text-[#15294a]'
                      : 'text-[#596675] hover:bg-atlas-paper',
                  ].join(' ')}
                >
                  <span
                    className="block truncate text-xs font-medium"
                    title={kpTitleAttr(kp) ?? kp.name}
                  >
                    {kpDisplayTitle(kp)}
                  </span>
                  <span className="mt-1 flex items-center gap-2 text-[10px] text-[#888f93]">
                    <span>
                      前置 {kp.prerequisite_count} · 误区 {kp.misconception_count}
                    </span>
                    <DifficultyBadge difficulty={kp.difficulty} />
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
