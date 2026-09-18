import { RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'

import { JobProgressPanel } from '@/components/materials/JobProgressPanel'
import type { ActiveUpload } from '@/components/materials/JobProgressPanel'
import { MaterialPreviewDrawer } from '@/components/materials/MaterialPreviewDrawer'
import { MaterialTable } from '@/components/materials/MaterialTable'
import { UploadDropzone } from '@/components/materials/UploadDropzone'
import { Button } from '@/components/ui/Button'
import { ErrorState, InlineError } from '@/components/ui/Feedback'
import { useJobsPolling } from '@/hooks/useJobsPolling'
import { useRequest } from '@/hooks/useRequest'
import { ApiError } from '@/lib/api'
import { api } from '@/lib/endpoints'
import type { Material, UploadRejected } from '@/lib/types'

/**
 * 素材工作台（P3 · D2 + D3 交付）。
 * 覆盖 SPEC §5.1 的 F1.1 上传 / F1.3 解析方式可见 / F1.6 素材清单 /
 * F1.7 进度与失败可见 / F1.8 Markdown 预览与页码定位；对应路由 /materials（api-spec §8）。
 */
export default function Materials() {
  const capabilities = useRequest(() => api.capabilities(), [])
  const materialsReq = useRequest(() => api.listMaterials(), [])

  const [activeUploads, setActiveUploads] = useState<ActiveUpload[]>([])
  const [rejected, setRejected] = useState<UploadRejected[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [preview, setPreview] = useState<Material | null>(null)

  const jobIds = useMemo(() => activeUploads.map((item) => item.job_id), [activeUploads])

  // 任务终结后刷新素材清单，拿到最终状态与质量分
  const { jobs, error: jobError } = useJobsPolling(jobIds, {
    onSettled: () => {
      void materialsReq.reload()
    },
  })

  const materials: Material[] = materialsReq.data?.items ?? []

  const stats = useMemo(() => {
    const parsing = materials.filter((m) => m.status === 'parsing' || m.status === 'pending').length
    const uncertain = materials.reduce((sum, m) => sum + m.uncertain_count, 0)
    const failed = materials.filter((m) => m.status === 'failed').length
    return { total: materials.length, parsing, uncertain, failed }
  }, [materials])

  const handleFiles = async (files: File[]) => {
    setUploading(true)
    setUploadError(null)
    try {
      const result = await api.uploadMaterials(files)
      setRejected(result.rejected)
      setActiveUploads((prev) => [
        ...prev,
        ...result.accepted.map((item) => ({ job_id: item.job_id, filename: item.filename })),
      ])
      if (result.accepted.length > 0) void materialsReq.reload()
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '上传失败，请稍后重试。'
      setUploadError(message)
    } finally {
      setUploading(false)
    }
  }

  const handleReparse = async (id: string) => {
    const target = materials.find((m) => m.id === id)
    setBusyId(id)
    setUploadError(null)
    try {
      const { job_id } = await api.reparseMaterial(id)
      setActiveUploads((prev) => [...prev, { job_id, filename: target?.filename ?? id }])
      void materialsReq.reload()
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : '重新解析失败。')
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (id: string) => {
    const target = materials.find((m) => m.id === id)
    if (!window.confirm(`确认删除素材「${target?.filename ?? id}」及其级联数据？此操作不可撤销。`)) return
    setBusyId(id)
    setUploadError(null)
    try {
      await api.deleteMaterial(id)
      void materialsReq.reload()
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : '删除失败。')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {/* 上传区 */}
      <section className="space-y-3">
        <UploadDropzone
          onFiles={handleFiles}
          uploading={uploading}
          capabilities={capabilities.data}
          disabled={uploading}
        />

        {uploadError && <InlineError>{uploadError}</InlineError>}

        {rejected.length > 0 && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3">
            <div className="mb-1.5 text-xs font-medium text-amber-800">
              {rejected.length} 个文件未被接受
            </div>
            <ul className="space-y-1">
              {rejected.map((item) => (
                <li key={item.filename} className="text-xs text-amber-700">
                  <span className="font-medium">{item.filename}</span>：{item.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* 解析进度 */}
      <JobProgressPanel
        items={activeUploads}
        jobs={jobs}
        onDismiss={() => setActiveUploads([])}
      />
      {jobError && <InlineError>{jobError}</InlineError>}

      {/* 素材清单 */}
      <section className="xizhi-card">
        <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <div className="flex items-baseline gap-3">
            <h2 className="text-sm font-semibold text-slate-800">素材清单</h2>
            <span className="text-xs text-slate-400">
              共 {stats.total} 份
              {stats.parsing > 0 && ` · 解析中 ${stats.parsing}`}
              {stats.failed > 0 && ` · 失败 ${stats.failed}`}
              {stats.uncertain > 0 && ` · 存疑 ${stats.uncertain} 处`}
            </span>
          </div>
          <Button
            variant="secondary"
            size="sm"
            loading={materialsReq.loading}
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => void materialsReq.reload()}
          >
            刷新
          </Button>
        </header>

        <div className="p-1">
          {materialsReq.error ? (
            <ErrorState message={materialsReq.error} onRetry={() => void materialsReq.reload()} />
          ) : (
            <MaterialTable
              materials={materials}
              loading={materialsReq.loading && materials.length === 0}
              busyId={busyId}
              onPreview={setPreview}
              onReparse={handleReparse}
              onDelete={handleDelete}
            />
          )}
        </div>
      </section>

      {preview && <MaterialPreviewDrawer material={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}
