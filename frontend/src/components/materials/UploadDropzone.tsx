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
        'flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
        dragging ? 'border-brand-400 bg-brand-50/70' : 'border-slate-300 bg-white hover:border-brand-300 hover:bg-slate-50',
        disabled || uploading ? 'cursor-not-allowed opacity-70' : '',
      ].join(' ')}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        className="hidden"
        onChange={(e) => {
          emit(e.target.files)
          e.target.value = ''
        }}
      />

      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-50 text-brand-600">
        {uploading ? <Spinner className="h-5 w-5" /> : <Upload className="h-5 w-5" aria-hidden />}
      </div>

      <div className="text-sm font-medium text-slate-700">
        {uploading ? '正在上传…' : '拖拽文件到此处，或点击选择'}
      </div>

      <div className="text-xs text-slate-400">
        支持 {typeHint} · 单文件 ≤ {maxMb}MB · 可多选
      </div>

      {unsupportedExt.length > 0 && (
        <div className="text-xs text-amber-600">
          暂不支持 {unsupportedExt.join(' / ')}（本版本聚焦图文材料解析）
        </div>
      )}
    </div>
  )
}
