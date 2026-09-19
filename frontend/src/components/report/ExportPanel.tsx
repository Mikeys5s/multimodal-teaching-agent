import { Download, FileJson, FileSpreadsheet } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { InlineError } from '@/components/ui/Feedback'
import { ApiError } from '@/lib/api'
import { api } from '@/lib/endpoints'

/** 本地日期戳，如 2026-09-18 */
function dateStamp(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * 触发浏览器下载：Blob + URL.createObjectURL + <a download>。
 * CSV 需要在调用方自行加 UTF-8 BOM，否则 Excel 会把中文识别成乱码。
 */
function triggerDownload(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message
  const message = (err as Error)?.message
  return message ? `导出失败：${message}` : fallback
}

/**
 * 导出区（api-spec §4.5 / 端点 17）。
 * 两个分支的响应性质不同：`format=json` 是 JSON 包封（走 request），
 * `format=csv` 是**原始 text/csv**（非 JSON 例外，标识走 `X-Request-ID` 响应头）——
 * 所以 CSV 拿到的是纯文本，直接落盘即可，不要再 JSON.parse。
 */
export function ExportPanel() {
  const [busy, setBusy] = useState<'csv' | 'json' | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleCsv = async () => {
    setBusy('csv')
    setError(null)
    setMessage(null)
    try {
      const csv = await api.exportKnowledgePointsCsv()
      // UTF-8 BOM：Excel 打开中文 CSV 才不会乱码
      triggerDownload(
        `knowledge-points-${dateStamp()}.csv`,
        `\uFEFF${csv}`,
        'text/csv;charset=utf-8',
      )
      const rows = csv.trim() ? csv.trim().split(/\r?\n/).length - 1 : 0
      setMessage(`CSV 已开始下载（含表头，约 ${Math.max(rows, 0)} 行数据，已加 UTF-8 BOM）。`)
    } catch (err) {
      setError(errorMessage(err, '导出 CSV 失败，请确认后端已启动后重试。'))
    } finally {
      setBusy(null)
    }
  }

  const handleJson = async () => {
    setBusy('json')
    setError(null)
    setMessage(null)
    try {
      const items = await api.exportKnowledgePointsJson()
      triggerDownload(
        `knowledge-points-${dateStamp()}.json`,
        JSON.stringify(items, null, 2),
        'application/json;charset=utf-8',
      )
      setMessage(`JSON 已开始下载（${items.length} 条知识点，含逐字溯源字段）。`)
    } catch (err) {
      setError(errorMessage(err, '导出 JSON 失败，请确认后端已启动后重试。'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="xizhi-card">
      <header className="flex items-baseline gap-3 border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-800">导出知识点</h2>
        <span className="text-xs text-slate-400">
          GET /api/export/knowledge-points · CSV 与 JSON 双格式，均含溯源列
        </span>
      </header>

      <div className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            size="sm"
            loading={busy === 'csv'}
            disabled={busy !== null}
            icon={<FileSpreadsheet className="h-3.5 w-3.5" />}
            onClick={() => void handleCsv()}
          >
            导出 CSV
          </Button>
          <Button
            size="sm"
            variant="secondary"
            loading={busy === 'json'}
            disabled={busy !== null}
            icon={<FileJson className="h-3.5 w-3.5" />}
            onClick={() => void handleJson()}
          >
            导出 JSON
          </Button>
          <span className="text-[11px] text-slate-400">
            文件名形如 knowledge-points-{dateStamp()}.csv，CSV 带 UTF-8 BOM，Excel 可直接打开中文。
          </span>
        </div>

        {message && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald-100 bg-emerald-50/70 px-3 py-2 text-xs text-emerald-700">
            <Download className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>{message}</span>
          </div>
        )}
        {error && <InlineError>{error}</InlineError>}
      </div>
    </section>
  )
}
