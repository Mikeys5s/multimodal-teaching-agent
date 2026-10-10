import { RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ExtractPanel } from '@/components/materials/ExtractPanel'
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
 * P3 追加 Stage 2 入口：知识点抽取为异步任务（202 + job_id），进度见 ExtractPanel。
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
      {/* 页头：编辑式标题 + 一个主操作（选择文件 → 打开上传区的文件选择器） */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="atlas-eyebrow">
            <span className="idx">02</span> SOURCE LIBRARY / MATERIALS
          </div>
          <h2 className="atlas-h1 mt-2">让材料保留来处。</h2>
          <p className="mt-2 max-w-[560px] text-[13px] leading-relaxed text-atlas-muted">
            上传后可追踪解析、抽取和复核状态。每个知识点都应能回到原文。
          </p>
        </div>
        <Button
          disabled={uploading}
          onClick={() => document.getElementById('materials-file-input')?.click()}
        >
          选择文件
        </Button>
      </div>

      {/* 上传区 + 流程说明（材质对比：蓝灰上传面 × 深蓝说明卡） */}
      <div className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
        <section className="space-y-3">
          <UploadDropzone
            onFiles={handleFiles}
            uploading={uploading}
            capabilities={capabilities.data}
            disabled={uploading}
          />

          {uploadError && <InlineError>{uploadError}</InlineError>}

          {rejected.length > 0 && (
            <div className="rounded-xl border border-warning-line bg-warning-soft p-3">
              <div className="mb-1.5 text-xs font-medium text-warning">
                {rejected.length} 个文件未被接受
              </div>
              <ul className="space-y-1">
                {rejected.map((item) => (
                  <li key={item.filename} className="text-xs text-warning">
                    <span className="font-medium">{item.filename}</span>：{item.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <aside className="atlas-navy-panel !rounded-2xl flex flex-col justify-between bg-atlas-ink2 p-5">
          <div
            aria-hidden
            className="pointer-events-none absolute -right-20 -top-14 h-40 w-40 rounded-full border border-lime/35 shadow-[0_0_0_18px_rgba(217,237,131,0.06),0_0_0_40px_rgba(217,237,131,0.04)]"
          />
          <div className="relative z-10">
            <div className="atlas-eyebrow !text-[#aeb9c7]">
              <span className="idx">01</span> PROCESS NOTE
            </div>
            <h3 className="mt-3 max-w-[240px] text-lg font-semibold leading-snug tracking-tight">
              先确认解析质量，再生成知识结构。
            </h3>
            <p className="mt-2.5 max-w-[250px] text-xs leading-relaxed text-[#aeb9c7]">
              解析失败的素材保留在清单里。修复并重试，不会静默丢弃原文件。
            </p>
          </div>
          <Link
            to="/report"
            className="relative z-10 mt-4 self-start text-xs text-lime transition-colors duration-120 hover:text-[#e4f6a2]"
          >
            查看解析质量说明 ↗
          </Link>
        </aside>
      </div>

      {/* 解析进度 */}
      <JobProgressPanel
        items={activeUploads}
        jobs={jobs}
        onDismiss={() => setActiveUploads([])}
      />
      {jobError && <InlineError>{jobError}</InlineError>}

      {/* 素材清单（材料档案） */}
      <section className="atlas-sheet-panel">
        <header className="flex items-center justify-between border-b border-atlas-line bg-atlas-paper2/60 px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <h3 className="text-base font-semibold text-atlas-ink">
              材料档案
              <span className="ml-2 text-xs font-normal text-atlas-muted">/ {stats.total} sources</span>
            </h3>
            <span className="text-xs text-atlas-muted">
              {stats.parsing > 0 && `解析中 ${stats.parsing} · `}
              {stats.failed > 0 && `失败 ${stats.failed} · `}
              {stats.uncertain > 0 ? `存疑 ${stats.uncertain} 处` : '按最近处理时间排序'}
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

      {/* 知识点抽取（Stage 2 入口）：异步任务 + 轮询进度 + 完成后去图谱/路径 */}
      <ExtractPanel
        materials={materials}
        loading={materialsReq.loading}
        materialsError={materials.length === 0 ? materialsReq.error : null}
        onReloadMaterials={() => void materialsReq.reload()}
        onJobSettled={() => {
          void materialsReq.reload()
        }}
      />

      {/* key 绑定素材 id：切换素材时重置抽屉内部状态（页签、定位页、复制提示） */}
      {preview && (
        <MaterialPreviewDrawer key={preview.id} material={preview} onClose={() => setPreview(null)} />
      )}
    </div>
  )
}
