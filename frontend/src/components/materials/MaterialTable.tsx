import { ChevronDown, ChevronRight, Eye, FileText, RefreshCw, Trash2 } from 'lucide-react'
import { Fragment, useState } from 'react'

import { StatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { EmptyState, LoadingState } from '@/components/ui/Feedback'
import { UncertainNotes } from '@/components/materials/UncertainNotes'
import { PARSE_METHOD_LABEL, SOURCE_TYPE_LABEL, formatBytes, formatDateTime, formatScore } from '@/lib/format'
import type { Material } from '@/lib/types'

export interface MaterialTableProps {
  materials: Material[]
  loading?: boolean
  busyId?: string | null
  onPreview: (material: Material) => void
  onReparse: (id: string) => void
  onDelete: (id: string) => void
}

const HEADERS = ['', '文件名', '类型', '大小', '解析方式', '页数', '状态', '质量分', '存疑处', '操作']

/**
 * 素材清单（api-spec §3.2「这就是素材清单的数据源，字段设计直接对应 A1-4 验收」）。
 * 字段与 Material 类型一一对应，不额外加工；存疑处可展开查看明细。
 * 桌面为表格；手机改为字段堆叠的列表项（首要识别字段=文件名+状态保持可见），禁止整页横滚。
 */
export function MaterialTable({ materials, loading = false, busyId = null, onPreview, onReparse, onDelete }: MaterialTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (loading) return <LoadingState label="正在加载素材清单…" />

  if (materials.length === 0) {
    return (
      <EmptyState
        title="还没有素材"
        description="上传 PDF / Word / PPT / 图片，系统将解析为带页码锚点的 Markdown，并给出素材清单。"
      />
    )
  }

  const qualityText = (m: Material) =>
    m.status === 'done' || m.status === 'partial' ? formatScore(m.quality_score) : '—'

  return (
    <>
      {/* 桌面表格（≥lg；平板用堆叠列表，避免容器内横滚找操作列） */}
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-atlas-line bg-atlas-paper2 text-left text-xs font-semibold uppercase tracking-wider text-atlas-muted">
              {HEADERS.map((header, index) => (
                <th key={index} className="whitespace-nowrap px-2 py-2.5">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {materials.map((material) => {
              const isOpen = expanded.has(material.id)
              const busy = busyId === material.id

              return (
                <Fragment key={material.id}>
                  <tr className="border-b border-[#e7e1d6] hover:bg-atlas-paper/60">
                    <td className="w-8 px-2 py-3">
                      <button
                        className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-30"
                        onClick={() => toggle(material.id)}
                        disabled={material.uncertain_notes.length === 0}
                        aria-label={isOpen ? '收起存疑处' : '展开存疑处'}
                        title={material.uncertain_notes.length === 0 ? '无存疑处' : '查看存疑处'}
                      >
                        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                    </td>
                    <td className="max-w-[220px] px-2 py-3">
                      <div className="flex items-center gap-2.5">
                        <span className="flex h-8 w-7 shrink-0 items-center justify-center rounded-md border border-[#d8d1c4] bg-[#fffaf0] text-coral" aria-hidden>
                          <FileText className="h-3.5 w-3.5" />
                        </span>
                        <span className="min-w-0">
                          <button
                            className="block max-w-full truncate text-left text-sm font-medium text-slate-700 hover:text-brand-600 hover:underline"
                            title={`${material.filename}（点击预览解析结果）`}
                            onClick={() => onPreview(material)}
                          >
                            {material.filename}
                          </button>
                          <span className="block text-xs text-slate-400">{formatDateTime(material.created_at)}</span>
                        </span>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-3 text-slate-600">
                      {SOURCE_TYPE_LABEL[material.source_type] ?? material.source_type}
                    </td>
                    <td className="whitespace-nowrap px-2 py-3 tabular-nums text-slate-600">
                      {formatBytes(material.size_bytes)}
                    </td>
                    <td className="whitespace-nowrap px-2 py-3 text-slate-600">
                      {PARSE_METHOD_LABEL[material.parse_method] ?? material.parse_method}
                    </td>
                    <td className="whitespace-nowrap px-2 py-3 tabular-nums text-slate-600">
                      {material.page_count || '—'}
                    </td>
                    <td className="whitespace-nowrap px-2 py-3">
                      <StatusBadge status={material.status} />
                    </td>
                    <td className="whitespace-nowrap px-2 py-3 tabular-nums text-slate-600">
                      {qualityText(material)}
                    </td>
                    <td className="whitespace-nowrap px-2 py-3">
                      {material.uncertain_count > 0 ? (
                        <button
                          className="rounded-md bg-warning-soft px-2 py-0.5 text-xs font-medium text-warning hover:bg-warning-line/60"
                          onClick={() => toggle(material.id)}
                        >
                          {material.uncertain_count} 处
                        </button>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-2 py-3">
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Eye className="h-3.5 w-3.5" />}
                          onClick={() => onPreview(material)}
                          title="预览解析结果（可跳转页码）"
                        >
                          预览
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={busy}
                          icon={<RefreshCw className="h-3.5 w-3.5" />}
                          onClick={() => onReparse(material.id)}
                          title="重新解析"
                        >
                          重试
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 className="h-3.5 w-3.5" />}
                          onClick={() => onDelete(material.id)}
                          title="删除素材"
                          aria-label={`删除素材 ${material.filename}`}
                          className="text-danger hover:bg-danger-soft"
                        />
                      </div>
                    </td>
                  </tr>

                  {isOpen && (
                    <tr className="border-b border-[#e7e1d6] bg-atlas-paper/60">
                      <td />
                      <td colSpan={HEADERS.length - 1} className="px-2 py-3">
                        <div className="mb-2 text-xs font-medium text-slate-500">
                          存疑处（{material.uncertain_notes.length}）
                        </div>
                        <UncertainNotes notes={material.uncertain_notes} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 手机堆叠列表（<md）：文件名 + 状态为第一行，操作保持 44px 触控 */}
      <ul className="divide-y divide-[#e7e1d6] lg:hidden">
        {materials.map((material) => {
          const isOpen = expanded.has(material.id)
          const busy = busyId === material.id
          return (
            <li key={material.id} className="px-2 py-3">
              <div className="flex items-start justify-between gap-2">
                <button
                  className="min-w-0 flex-1 break-all text-left text-sm font-medium text-slate-800 hover:text-brand-600"
                  title={`${material.filename}（点击预览解析结果）`}
                  onClick={() => onPreview(material)}
                >
                  {material.filename}
                </button>
                <StatusBadge status={material.status} />
              </div>
              <div className="mt-1 text-xs text-slate-400">{formatDateTime(material.created_at)}</div>

              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <div className="flex gap-1.5">
                  <dt className="text-slate-400">类型</dt>
                  <dd className="text-slate-600">{SOURCE_TYPE_LABEL[material.source_type] ?? material.source_type}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-slate-400">大小</dt>
                  <dd className="tabular-nums text-slate-600">{formatBytes(material.size_bytes)}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-slate-400">解析方式</dt>
                  <dd className="text-slate-600">{PARSE_METHOD_LABEL[material.parse_method] ?? material.parse_method}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-slate-400">页数</dt>
                  <dd className="tabular-nums text-slate-600">{material.page_count || '—'}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-slate-400">质量分</dt>
                  <dd className="tabular-nums text-slate-600">{qualityText(material)}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="text-slate-400">存疑处</dt>
                  <dd>
                    {material.uncertain_count > 0 ? (
                      <button
                        className="rounded-md bg-warning-soft px-1.5 py-0.5 text-xs font-medium text-warning"
                        onClick={() => toggle(material.id)}
                      >
                        {material.uncertain_count} 处
                      </button>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </dd>
                </div>
              </dl>

              <div className="mt-2 flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Eye className="h-3.5 w-3.5" />}
                  onClick={() => onPreview(material)}
                >
                  预览
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  loading={busy}
                  icon={<RefreshCw className="h-3.5 w-3.5" />}
                  onClick={() => onReparse(material.id)}
                >
                  重试
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                  onClick={() => onDelete(material.id)}
                  aria-label={`删除素材 ${material.filename}`}
                  className="text-danger hover:bg-danger-soft"
                />
              </div>

              {isOpen && (
                <div className="mt-2 rounded-lg bg-slate-50 p-3">
                  <div className="mb-2 text-xs font-medium text-slate-500">
                    存疑处（{material.uncertain_notes.length}）
                  </div>
                  <UncertainNotes notes={material.uncertain_notes} />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </>
  )
}
