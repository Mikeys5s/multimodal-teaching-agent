import { Placeholder } from '@/components/layout/Placeholder'

export default function Report() {
  return (
    <Placeholder
      title="质量报告"
      milestone="D4（9/19）起可跑，D10 收口"
      note="把工程严谨度做成可见的一页：解析成功率、字段完备率、溯源覆盖率、DAG 环数 / 剪除数 / 冲突数、越界拒答次数。这是 Demo 视频里的亮点镜头，也是各项验收指标的集中呈现。"
      endpoints={['GET /api/report/quality', 'GET /api/export/knowledge-points']}
    />
  )
}
