import { Check, Copy, FileText, ListChecks, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { QuestionsPanel } from '@/components/materials/QuestionsPanel'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { ApiError } from '@/lib/api'
import { api } from '@/lib/endpoints'
import { PARSE_METHOD_LABEL } from '@/lib/format'
import type { Block, Material } from '@/lib/types'

/** OCR 置信度低于此值的块，显式标注（不掩盖解析短板） */
const LOW_CONFIDENCE = 0.85

const HEADING_CLASS = [
  '',
  'text-xl font-semibold text-slate-900',
  'text-lg font-semibold text-slate-900',
  'text-base font-semibold text-slate-800',
  'text-sm font-semibold text-slate-800',
  'text-sm font-medium text-slate-700',
  'text-xs font-medium text-slate-700',
]

function BlockView({ block }: { block: Block }) {
  const lowConfidence =
    block.ocr_confidence !== null && block.ocr_confidence < LOW_CONFIDENCE

  const body =
    block.block_type === 'heading' && block.heading_level
      ? block.content_md
      : block.content_md

  return (
    <div className="relative">
      {block.block_type === 'heading' && block.heading_level ? (
        <div className={`mt-4 mb-1 ${HEADING_CLASS[Math.min(Math.max(block.heading_level, 1), 6)]}`}>
          {body}
        </div>
      ) : (
        <p className="mb-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">{body}</p>
      )}

      {lowConfidence && (
        <div className="mb-2 inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">
          识别置信度 {Math.round((block.ocr_confidence ?? 0) * 100)}% · 建议人工核对
        </div>
      )}
    </div>
  )
}

export interface MaterialPreviewDrawerProps {
  material: Material
  onClose: () => void
}

/**
 * 素材解析结果预览抽屉（SPEC §5.1 F1.8）。
 * 数据源：GET /api/materials/{id}/blocks（api-spec §3.3 明确它是「Markdown 预览数据源」）。
 * 点击右侧页码 → 滚动定位到该页首块，实现「点击可定位到对应页码」。
 *
 * 另一个页签「抽出的题目」走 GET /api/materials/{id}/questions，见 QuestionsPanel。
 * 两个页签的数据源互相独立，题目接口失败不会影响 Markdown 预览。
 */
export function MaterialPreviewDrawer({ material, onClose }: MaterialPreviewDrawerProps) {
  const blocksReq = useRequest(() => api.listBlocks(material.id), [material.id])
  const [tab, setTab] = useState<'blocks' | 'questions'>('blocks')
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<string | null>(null)
  const [activePage, setActivePage] = useState<number | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const blocks = blocksReq.data ?? []

  const grouped = useMemo(() => {
    const map = new Map<number, Block[]>()
    for (const block of blocks) {
      const list = map.get(block.page_no) ?? []
      list.push(block)
      map.set(block.page_no, list)
    }
    return Array.from(map.entries()).sort((a, b) => a[0] - b[0])
  }, [blocks])

  const jumpTo = (page: number) => {
    setActivePage(page)
    const target = scrollRef.current?.querySelector(`[data-page="${page}"]`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const copyMarkdown = async () => {
    setCopyError(null)
    try {
      const markdown = await api.getMarkdown(material.id)
      await navigator.clipboard.writeText(markdown)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch (err) {
      setCopyError(err instanceof ApiError ? err.message : '复制失败，请稍后重试。')
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/30" onClick={onClose} />

      <div className="relative flex h-full w-[860px] max-w-full flex-col border-l border-slate-200 bg-white shadow-2xl">
        {/* 头部 */}
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
              <h2 className="truncate text-sm font-semibold text-slate-800" title={material.filename}>
                {material.filename}
              </h2>
            </div>
            <div className="mt-0.5 text-xs text-slate-400">
              {PARSE_METHOD_LABEL[material.parse_method] ?? material.parse_method} · 共{' '}
              {material.page_count} 页 · 解析正文 {material.char_count} 字
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              onClick={copyMarkdown}
            >
              {copied ? '已复制' : '复制 Markdown'}
            </Button>
            <button
              className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              onClick={onClose}
              aria-label="关闭预览"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        {copyError && (
          <div className="shrink-0 border-b border-red-100 bg-red-50/70 px-5 py-2 text-xs text-red-700">
            {copyError}
          </div>
        )}

        {/* 页签：解析正文 / 抽出的题目 */}
        <div
          className="flex shrink-0 gap-1 border-b border-slate-200 px-4"
          role="tablist"
          aria-label="预览内容切换"
        >
          {(
            [
              { key: 'blocks', label: '解析正文', icon: <FileText className="h-3.5 w-3.5" /> },
              { key: 'questions', label: '抽出的题目', icon: <ListChecks className="h-3.5 w-3.5" /> },
            ] as const
          ).map((item) => (
            <button
              key={item.key}
              role="tab"
              aria-selected={tab === item.key}
              onClick={() => setTab(item.key)}
              className={[
                '-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors',
                tab === item.key
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-slate-500 hover:text-slate-700',
              ].join(' ')}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>

        {/* 正文 + 页码导航 */}
        <div className="flex min-h-0 flex-1">
          {tab === 'questions' ? (
            <div className="min-w-0 flex-1 overflow-auto bg-slate-50/50 px-5 py-4">
              <QuestionsPanel materialId={material.id} />
            </div>
          ) : (
            <>
              <div ref={scrollRef} className="min-w-0 flex-1 overflow-auto px-6 py-4">
                {blocksReq.loading && blocks.length === 0 && <LoadingState label="正在加载解析结果…" />}

                {blocksReq.error && (
                  <ErrorState message={blocksReq.error} onRetry={() => void blocksReq.reload()} />
                )}

                {!blocksReq.loading && !blocksReq.error && blocks.length === 0 && (
                  <EmptyState
                    title="暂无解析结果"
                    description="该素材可能仍在解析中，或解析未产出可预览的文本块。"
                  />
                )}

                {grouped.map(([page, pageBlocks]) => (
                  <section key={page} data-page={page} className="mb-8 scroll-mt-4">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                        第 {page} 页
                      </span>
                      <span className="h-px flex-1 bg-slate-100" />
                    </div>
                    {pageBlocks.map((block) => (
                      <BlockView key={block.id} block={block} />
                    ))}
                  </section>
                ))}
              </div>

              {/* 页码导航（点击定位） */}
              <aside className="w-[76px] shrink-0 overflow-auto border-l border-slate-200 bg-slate-50/60 py-3">
                <div className="mb-2 px-2 text-[11px] text-slate-400">页码</div>
                <div className="flex flex-col items-stretch gap-0.5 px-2">
                  {grouped.map(([page]) => (
                    <button
                      key={page}
                      onClick={() => jumpTo(page)}
                      className={[
                        'rounded px-2 py-1 text-xs tabular-nums transition-colors',
                        activePage === page
                          ? 'bg-brand-100 font-medium text-brand-700'
                          : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700',
                      ].join(' ')}
                    >
                      {page}
                    </button>
                  ))}
                </div>
              </aside>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
