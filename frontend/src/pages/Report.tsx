import { RefreshCw } from 'lucide-react'

import { AuditSheet, ReportNote } from '@/components/report/AuditSheet'
import { ExportPanel } from '@/components/report/ExportPanel'
import { HealthSelfCheck } from '@/components/report/HealthSelfCheck'
import { MetricsStrip, ReportBanner } from '@/components/report/ReportOverview'
import { buildReportMetrics } from '@/components/report/buildMetrics'
import { Button } from '@/components/ui/Button'
import { ErrorState, InlineError, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import type { QualityReport } from '@/lib/types'

/**
 * 质量报告页（F4.3 / api-spec §4.6「GET /api/report/quality」）。
 * 把工程严谨度做成可见的一页：指标全部以**数值 + 进度条 + 对应验收红线**呈现，
 * 未达标显式标红；面向教师/学习者用中文概念名，不再泄漏原始工程字段名。
 * 构图（Learning Atlas v2）：页头 → 深蓝总览横幅（质量环）→ 核心指标带 →
 * 暖纸校验清单 + 读法 NOTE → 部署自检与导出。
 */
export default function Report() {
  const reportReq = useRequest(() => api.getQualityReport(), [])
  const report = reportReq.data
  const ready = isCompleteReport(report)
  const metrics = ready && report ? buildReportMetrics(report) : null

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      {/* 页头：编辑式标题 + 刷新（次级操作） */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="atlas-eyebrow">
            <span className="idx">06</span> QUALITY REPORT / EVIDENCE
          </div>
          <h2 className="atlas-h1 mt-2">质量，要有出处。</h2>
          <p className="mt-2 max-w-[560px] text-[13px] leading-relaxed text-atlas-muted">
            把结构、覆盖、溯源与可达性放在同一张审查地图上；未达到的项目也要清楚标记。
          </p>
        </div>
        <Button
          variant="secondary"
          className="shrink-0"
          loading={reportReq.loading}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void reportReq.reload()}
        >
          刷新报告
        </Button>
      </div>

      {reportReq.error && !report && (
        <ErrorState message={reportReq.error} onRetry={() => void reportReq.reload()} />
      )}

      {!reportReq.error && !report && <LoadingState label="正在汇总质量指标…" />}

      {reportReq.error && report && <InlineError>{reportReq.error}（当前展示的是上一次成功的数据）</InlineError>}

      {report && !ready && (
        <InlineError>质量报告结构不完整，缺少 materials / knowledge_points / graph / qa 中的分区。</InlineError>
      )}

      {metrics && (
        <>
          <ReportBanner metrics={metrics.critical} />
          <MetricsStrip metrics={metrics.critical} />

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
            <AuditSheet metrics={metrics} />
            <ReportNote />
          </div>

          <div id="health-self-check" className="scroll-mt-6">
            <HealthSelfCheck />
          </div>

          <ExportPanel />
        </>
      )}
    </div>
  )
}

/** 运行时兜底：后端契约虽已冻结，但缺分区时不应直接把页面打崩 */
function isCompleteReport(report: QualityReport | null): report is QualityReport {
  if (!report) return false
  return Boolean(report.materials && report.knowledge_points && report.graph && report.qa)
}
