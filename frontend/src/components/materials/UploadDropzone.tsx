import { Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'

import { Spinner } from '@/components/ui/Feedback'
import type { Capabilities } from '@/lib/types'

export interface UploadDropzoneProps {
  onFiles: (files: File[]) => void
  uploading?: boolean
  capabilities: Capabilities | null
  disabled?: boolean
}

/**
 * 素材上传区（SPEC §5.1 F1.1：拖拽/点选多文件）。
 * 支持格式与大小上限来自 GET /api/meta/capabilities —— 不在前端硬编码（api-spec §2）。
 *
 * ⚠️ 线上实现与 api-spec §2 的描述**不一致**（2026-09-19 对线上实例逐字段核对发现）：
 *   文档承诺 `material_types`（每项含 `ext` / `label`）与 `unsupported_ext`，
 *   线上实际返回的是 `supported_material_types`（扩展名字符串数组）+ `parse_methods`（扩展名 → 中文说明）。
 *   所以这里**两种形状都读**，优先用实际返回的那种。
 *
 *   绝不能写成 `capabilities.material_types.flatMap(...)` —— 线上该字段是 `undefined`，
 *   后果是**整个素材页在渲染时直接白屏**。这类错只在真数据下才暴露，类型检查与构建都拦不住。
 */
export function UploadDropzone({ onFiles, uploading = false, capabilities, disabled = false }: UploadDropzoneProps) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const supportedExt = capabilities?.supported_material_types ?? []
  const legacyTypes = capabilities?.material_types ?? []
  const accept =
    (supportedExt.length > 0 ? supportedExt : legacyTypes.flatMap((t) => t.ext)).join(',') || undefined
  const maxMb = capabilities?.max_upload_mb ?? 50
  const unsupportedExt = capabilities?.unsupported_ext ?? []

  const emit = (list: FileList | null) => {
    if (!list || list.length === 0) return
    onFiles(Array.from(list))
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(false)
    if (disabled || uploading) return
    emit(e.dataTransfer.files)
  }

  const typeHint =
    supportedExt.length > 0
      ? supportedExt.join(' / ')
      : legacyTypes.length > 0
        ? legacyTypes.map((t) => t.label).join(' / ')
        : 'PDF / Word / PPT / 图片'

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled || uploading}
      onClick={() => !disabled && !uploading && inputRef.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && !disabled && !uploading) inputRef.current?.click()
      }}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled && !uploading) setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={[
        'relative flex min-h-[210px] cursor-pointer flex-col items-start gap-5 overflow-hidden rounded-2xl border px-6 py-6 transition-all duration-220 sm:flex-row sm:items-center sm:gap-7 sm:px-8',
        dragging
          ? '-translate-y-0.5 border-brand-400 bg-[#cfddf2] shadow-panel'
          : 'border-[#b8c9e7] bg-[#dce5f5] hover:border-[#9db4dd]',
        disabled || uploading ? 'cursor-not-allowed opacity-80' : '',
      ].join(' ')}
    >
      {/* 细点阵材质（左强右淡，纯装饰） */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 [background-image:radial-gradient(#5672aa44_0.8px,transparent_0.8px)] [background-size:14px_14px] [mask-image:linear-gradient(90deg,black,transparent_86%)]"
      />

      <input
        ref={inputRef}
        id="materials-file-input"
        type="file"
        multiple
        accept={accept}
        className="hidden"
        onChange={(e) => {
          emit(e.target.files)
          e.target.value = ''
        }}
      />

      {/* 轨道圆环（拖入时轻微抬起；旋转属装饰性氛围，与真实任务状态无关） */}
      <div className="relative z-10 grid h-[104px] w-[104px] shrink-0 place-items-center rounded-full border border-[#7590ca] bg-white/35">
        <span aria-hidden className="atlas-spin absolute inset-2 rounded-full border border-dashed border-[#8098c8]" />
        <span aria-hidden className="atlas-spin-rev absolute -inset-2 rounded-full border border-dashed border-[#b0715f]" />
        {uploading ? (
          <Spinner className="h-6 w-6 text-brand-600" />
        ) : (
          <Upload className="h-7 w-7 text-brand-600" aria-hidden />
        )}
      </div>

      <div className="relative z-10 min-w-0">
        <div className="atlas-eyebrow !text-[#49628d]">DROP A SOURCE / 01</div>
        <h3 className="mt-2 text-xl font-bold tracking-tight text-atlas-ink">
          {uploading ? '正在上传…' : '把一份材料，放进知识地图。'}
        </h3>
        <p className="mt-1.5 text-xs leading-relaxed text-[#536987]">
          拖放到此处，或从设备中选择。支持 {typeHint}。
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white shadow-[0_8px_20px_rgba(49,92,255,0.22)]">
            <Upload className="h-4 w-4" aria-hidden />
            浏览文件
          </span>
          <span className="text-xs text-[#647795]">单文件 ≤ {maxMb}MB · 可多选</span>
        </div>
        {unsupportedExt.length > 0 && (
          <div className="mt-2 text-xs text-warning">
            暂不支持 {unsupportedExt.join(' / ')}（本版本聚焦图文材料解析）
          </div>
        )}
      </div>
    </div>
  )
}
