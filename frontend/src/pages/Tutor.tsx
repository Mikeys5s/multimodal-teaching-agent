import { Placeholder } from '@/components/layout/Placeholder'

export default function Tutor() {
  return (
    <Placeholder
      title="答疑辅导"
      milestone="D8（9/23）"
      note="苏格拉底式引导的交互入口：SSE 流式回复、溯源卡片、右侧诊断面板（涉及知识点 / 卡在哪一步 / 下一步练习）。首轮只反问不给答案；连续两次答不上时明确提示并降级为直接讲解；检索不到时走拒答模板。"
      endpoints={[
        'POST /api/qa/sessions',
        'POST /api/qa/sessions/{id}/ask（SSE）',
        'GET /api/qa/sessions/{id}/state',
        'GET /api/qa/sessions/{id}/report',
      ]}
    />
  )
}
