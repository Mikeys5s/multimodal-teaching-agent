"""素材解析链路（归属：P1 · DakerDack）。

规划内容（SPEC §5.1 / §4.4）：
  PDF 文本版 -> PyMuPDF；DOCX -> python-docx；PPTX -> python-pptx
  扫描版/图片 -> PaddleOCR（纯本地）+ 人工校对
产物：带块锚点的 Markdown，落 material_blocks 表。

⚠️ 依赖装在可选组：pip install -e ".[parse]"
"""
