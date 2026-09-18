import { RefreshCw } from 'lucide-react'

import { ExportPanel } from '@/components/report/ExportPanel'
import { HealthSelfCheck } from '@/components/report/HealthSelfCheck'
import { MetricSection } from '@/components/report/MetricCard'
import { ReportOverview } from '@/components/report/ReportOverview'
import { buildReportMetrics } from '@/components/report/buildMetrics'
import { Button } from '@/components/ui/Button'
import { ErrorState, InlineError, LoadingState } from '@/components/ui/Feedback'
import { useRequest } from '@/hooks/useRequest'
import { api } from '@/lib/endpoints'
import type { QualityReport } from '@/lib/types'

/**
 * 质量报告页（F4.3 / api-spec §4.6「GET /api/report/quality」）。
 * 把工程严谨度做成可见的一页：四个分区的指标全部以
 * **数值 + 进度条 + 对应验收红线**呈现，未达标显式标红；
 * 另附「演示前自检」（health + pragma，含 foreign_keys 强制校验）与导出（CSV / JSON）。
 */
export default function Report() {
  const reportReq = useRequest(() => api.getQualityReport(), [])
  const report = reportReq.data
  const ready = isCompleteReport(report)
  const metrics = ready && report ? buildReportMetrics(report) : null

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <section className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-base font-semibold text-slate-800">质量报告</h1>
          <p className="mt-1 text-xs text-slate-500">
            每项指标都标注了它对应的验收红线（A2-1 / A2-3 / B1-1 / B1-2 / B1-5 与接地率），
            未达标会显式标红 —— 这一页给评委看的是「能不能过验收」，不是一组好看的数字。
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={reportReq.loading}
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void reportReq.reload()}
        >
          刷新
        </Button>
      </section>

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
          <ReportOverview metrics={metrics.critical} />

          <MetricSection
            title="素材解析"
            subtitle="materials —— 解析成功率、失败可见性、质量均分"
            metrics={metrics.materials}
          />

          <MetricSection
            title="知识点"
            subtitle="knowledge_points —— 三级结构、溯源覆盖、五要素完备、待复核"
            metrics={metrics.knowledgePoints}
          />

          <MetricSection
            title="知识图谱"
            subtitle="graph —— DAG 环数、边理由完备率、剪枝与冲突可见性"
            metrics={metrics.graph}
          />

          <MetricSection
            title="答疑辅导"
            subtitle="qa —— 接地率、拒答次数（拒答是能力，不是缺陷）"
            metrics={metrics.qa}
          />
        </>
      )}

      <HealthSelfCheck />

      <ExportPanel />
    </div>
  )
}

/** 运行时兜底：后端契约虽已冻结，但缺分区时不应直接把页面打崩 */
function isCompleteReport(report: QualityReport | null): report is QualityReport {
  if (!report) return false
  return Boolean(report.materials && report.knowledge_points && report.graph && report.qa)
}
