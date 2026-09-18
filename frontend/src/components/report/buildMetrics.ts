import type { MetricSpec } from './MetricCard'

import type { QualityReport } from '@/lib/types'

export interface ReportMetrics {
  materials: MetricSpec[]
  knowledgePoints: MetricSpec[]
  graph: MetricSpec[]
  qa: MetricSpec[]
  /** 顶部总览用：四条最关键的红线 */
  critical: MetricSpec[]
}

/** 核心红线 key（顶部「能否过验收」总览只关心这四条） */
export const CRITICAL_KEYS = [
  'structure_complete_rate',
  'grounding_rate',
  'cycle_count',
  'grounded_rate',
] as const

/**
 * 把 `QualityReport`（types.ts §5）翻译成「数值 + 进度条 + 验收红线」的指标清单。
 *
 * 红线口径全部来自 docs/api-spec.md §4.6 与 docs/innovation.md §6：
 *   A2-1 三级结构完整率 100% / A2-3 溯源覆盖率 100% / B1-2 DAG 环数 0 /
 *   B1-5 边理由完备率 100% / B1-1 前置边抽检合理率 ≥ 80%（对应 prerequisite_sampling_pass_rate）。
 */
export function buildReportMetrics(report: QualityReport): ReportMetrics {
  const m = report.materials
  const kp = report.knowledge_points
  const g = report.graph
  const qa = report.qa

  const materials: MetricSpec[] = [
    {
      key: 'materials_total',
      label: '素材总数 materials.total',
      redLine: null,
      targetText: '观测项',
      value: m.total,
      compare: 'info',
      note: '已入库的素材份数。',
    },
    {
      key: 'materials_done',
      label: '解析完成 materials.done',
      redLine: null,
      targetText: `占总数 ${fmtRatio(m.done, m.total)}`,
      value: m.done,
      compare: 'info',
      ratio: ratioOf(m.done, m.total),
      note: '完成解析的素材数；失败素材已在清单页可追溯原因。',
    },
    {
      key: 'materials_failed',
      label: '解析失败 materials.failed',
      redLine: null,
      targetText: '观测项',
      value: m.failed,
      compare: 'info',
      ratio: ratioOf(m.failed, m.total),
      note: '失败不等于静默丢弃：失败原因在素材清单逐条可见，可重新解析。',
    },
    {
      key: 'avg_quality_score',
      label: '解析质量均分 avg_quality_score',
      redLine: null,
      targetText: '观测项',
      value: m.avg_quality_score,
      compare: 'info',
      rate: true,
      note: '全部素材解析质量分的平均值；后端未产出时显示「暂缺」而非 0。',
    },
  ]

  const knowledgePoints: MetricSpec[] = [
    {
      key: 'kp_total',
      label: '知识点总数 knowledge_points.total',
      redLine: null,
      targetText: '观测项',
      value: kp.total,
      compare: 'info',
      note: '经三级结构与溯源门禁后入库的知识点数量。',
    },
    {
      key: 'structure_complete_rate',
      label: '知识点全部落在 章 / 节 / 知识点 三级上',
      redLine: 'A2-1 三级结构完整率',
      targetText: '目标 1.0（100%）',
      value: kp.structure_complete_rate,
      target: 1,
      compare: 'gte',
      rate: true,
      critical: true,
      note: 'DB 层 chapter_id / section_id NOT NULL 硬约束：没有归属章节的知识点不允许入库。',
    },
    {
      key: 'grounding_rate',
      label: '知识点带逐字原文片段的比例',
      redLine: 'A2-3 溯源覆盖率',
      targetText: '目标 1.0（100%）',
      value: kp.grounding_rate,
      target: 1,
      compare: 'gte',
      rate: true,
      critical: true,
      note: 'source_quote 非空 + 入库校验：知识点级溯源门禁，点得开、核得到原文。',
    },
    {
      key: 'five_field_complete_rate',
      label: '五要素完备率 five_field_complete_rate',
      redLine: null,
      targetText: '目标 1.0（100%）',
      value: kp.five_field_complete_rate,
      target: 1,
      compare: 'gte',
      rate: true,
      note: '名称 / 摘要 / 难度与理由 / 类型 / 溯源五要素齐备（A2-2 的支撑指标）。',
    },
    {
      key: 'needs_review_count',
      label: '待人工复核数 needs_review_count',
      redLine: null,
      targetText: '观测项（不追求为 0）',
      value: kp.needs_review_count,
      compare: 'info',
      ratio: ratioOf(kp.needs_review_count, kp.total),
      note: '「宁缺毋错」原则的体现：系统不确定时显式登记复核，而不是猜一个看起来完整的答案。',
    },
  ]

  const graph: MetricSpec[] = [
    {
      key: 'cycle_count',
      label: '依赖环数量 cycle_count',
      redLine: 'B1-2 DAG 环数',
      targetText: '必须为 0',
      value: g.cycle_count,
      target: 0,
      compare: 'eq',
      critical: true,
      note: '拓扑排序校验：只要有环，「先学 A 才能学 B、先学 B 才能学 A」的学习路径就无法生成。',
    },
    {
      key: 'reason_complete_rate',
      label: '前置边带非空理由的比例',
      redLine: 'B1-5 边理由完备率',
      targetText: '目标 1.0（100%）',
      value: g.reason_complete_rate,
      target: 1,
      compare: 'gte',
      rate: true,
      note: 'SQL 校验 reason 非空 —— 每条依赖边都说得清「为什么它是前置」，学习路径才可解释。',
    },
    {
      key: 'edge_count',
      label: '依赖边总数 graph.edge_count',
      redLine: null,
      targetText: '观测项',
      value: g.edge_count,
      compare: 'info',
      note: '图谱中的前置依赖边规模。',
    },
    {
      key: 'pruned_count',
      label: '因成环被剪除的边 pruned_count',
      redLine: null,
      targetText: '观测项',
      value: g.pruned_count,
      compare: 'info',
      ratio: ratioOf(g.pruned_count, g.edge_count),
      note: '「检出了 N 条会成环的边并已剪除」比只写「环数 0」更有说服力：证明真的在逐边做环检测。',
    },
    {
      key: 'conflict_count',
      label: '结构-语义冲突边 conflict_count',
      redLine: null,
      targetText: '观测项（不静默丢弃）',
      value: g.conflict_count,
      compare: 'info',
      ratio: ratioOf(g.conflict_count, g.edge_count),
      note: '语义宣称的依赖与章节先后矛盾时登记为待复核，冲突可见 = 歧义不掩盖。',
    },
    {
      key: 'prerequisite_sampling_pass_rate',
      label: '前置边人工抽检 pass_rate',
      redLine: 'B1-1 前置边抽检合理率',
      targetText: '目标 ≥ 0.8（80%）',
      value: g.prerequisite_sampling_pass_rate,
      target: 0.8,
      compare: 'gte',
      rate: true,
      note: '随机抽边人工判定「这条前置关系在教学上是否成立」；未抽检时显示「暂缺」。',
    },
  ]

  const qaMetrics: MetricSpec[] = [
    {
      key: 'grounded_rate',
      label: '回答中有原文支撑的比例',
      redLine: '接地率（幻觉率 0 的体现）',
      targetText: '目标 1.0（100%）',
      value: qa.grounded_rate,
      target: 1,
      compare: 'gte',
      rate: true,
      critical: true,
      note: '先检索再回答：每条回答都能回溯到知识点的原文片段，接地率 1.0 即对外可见的「零幻觉」。',
    },
    {
      key: 'refuse_count',
      label: '越界拒答次数 refuse_count',
      redLine: null,
      targetText: '观测项（不追求为 0）',
      value: qa.refuse_count,
      compare: 'info',
      note: '拒答是能力，不是缺陷：超出材料范围时明确说「答不了」，比编一个像样的答案是更可靠的工程行为。',
    },
    {
      key: 'session_count',
      label: '答疑会话数 qa.session_count',
      redLine: null,
      targetText: '观测项',
      value: qa.session_count,
      compare: 'info',
      note: '进入过苏格拉底式答疑的会话数。',
    },
    {
      key: 'turn_count',
      label: '答疑轮次 qa.turn_count',
      redLine: null,
      targetText: '观测项',
      value: qa.turn_count,
      compare: 'info',
      ratio: ratioOf(qa.refuse_count, qa.turn_count),
      note: `共 ${qa.turn_count} 轮问答，其中拒答 ${qa.refuse_count} 轮。`,
    },
  ]

  const all = [...materials, ...knowledgePoints, ...graph, ...qaMetrics]
  const critical = CRITICAL_KEYS.map((key) => all.find((spec) => spec.key === key)).filter(
    (spec): spec is MetricSpec => Boolean(spec),
  )

  return { materials, knowledgePoints, graph, qa: qaMetrics, critical }
}

function ratioOf(part: number, whole: number): number | undefined {
  if (!Number.isFinite(part) || !Number.isFinite(whole) || whole <= 0) return undefined
  return Math.max(0, Math.min(1, part / whole))
}

function fmtRatio(part: number, whole: number): string {
  const ratio = ratioOf(part, whole)
  return ratio === undefined ? '—' : `${Number((ratio * 100).toFixed(1))}%`
}
