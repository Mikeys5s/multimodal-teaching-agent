import { ChevronDown, ChevronRight, Eye, RefreshCw, Trash2 } from 'lucide-react'
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
 * 素材清单表（api-spec §3.2「这就是素材清单的数据源，字段设计直接对应 A1-4 验收」）。
 * 字段与 Material 类型一一对应，不额外加工；存疑处可展开查看明细。
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

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
            {HEADERS.map((header, index) => (
              <th key={index} className="whitespace-nowrap px-3 py-2 font-medium">
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
                <tr className="border-b border-slate-100 hover:bg-slate-50/70">
                  <td className="w-8 px-2 py-2">
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
                  <td className="max-w-[240px] px-3 py-2">
                    <button
                      className="block max-w-full truncate text-left font-medium text-slate-700 hover:text-brand-600 hover:underline"
                      title={`${material.filename}（点击预览解析结果）`}
                      onClick={() => onPreview(material)}
                    >
                      {material.filename}
                    </button>
                    <div className="text-xs text-slate-400">{formatDateTime(material.created_at)}</div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                    {SOURCE_TYPE_LABEL[material.source_type] ?? material.source_type}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-slate-600">
                    {formatBytes(material.size_bytes)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-600">
                    {PARSE_METHOD_LABEL[material.parse_method] ?? material.parse_method}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-slate-600">
                    {material.page_count || '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <StatusBadge status={material.status} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 tabular-nums text-slate-600">
                    {material.status === 'done' || material.status === 'partial' ? formatScore(material.quality_score) : '—'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {material.uncertain_count > 0 ? (
                      <button
                        className="rounded-md bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
                        onClick={() => toggle(material.id)}
                      >
                        {material.uncertain_count} 处
                      </button>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
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
                        className="text-red-500 hover:bg-red-50"
                      />
                    </div>
                  </td>
                </tr>

                {isOpen && (
                  <tr className="border-b border-slate-100 bg-slate-50/50">
                    <td />
                    <td colSpan={HEADERS.length - 1} className="px-3 py-3">
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
  )
}
