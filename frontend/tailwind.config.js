/** @type {import('tailwindcss').Config} */
// 析知 XiZhi 设计 token 集中定义（Learning Atlas v2 · 2026-10-10）
// - atlas：深夜蓝制图画布（ink）× 暖纸档案（paper/sheet）双材质；electric 为主行动色
// - brand：映射到 electric（#315cff 族），保持「唯一主行动色」语义与既有类名可用
// - lime/teal/coral：只作小面积路径/状态强调（深蓝底用亮色，纸面底用深色文字版 *_deep）
// - difficulty：难度 1–5（SPEC §5.2 F2.7 节点颜色映射难度）
// - status：素材/任务状态，与 api-spec §3.2 status 枚举一一对应
// - 语义色（success/warning/danger/info）：只承载状态含义，必须配文字/图标，不靠颜色单独传达
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Learning Atlas 双材质
        atlas: {
          ink: '#101c2e', // 深夜蓝制图画布（侧栏 / 主视觉 / 图谱 / 学习者气泡）
          ink2: '#192941', // 深面板（流程说明 / 原则板）
          ink3: '#263b57', // 来源 chip / 图谱节点描边层
          node: '#182a42', // 图谱节点卡底色
          nodeSel: '#213e61', // 图谱节点选中底色
          canvas: '#0e1929', // 图谱画布底色
          paper: '#f2efe7', // 页面暖纸底
          paper2: '#e7e3d8', // 次级纸面（表头 / 流程带 / 侧栏面板头）
          sheet: '#fffdf7', // 内容纸面（卡片 / 对话 / 表格）
          line: '#d6d0c3', // 纸面分隔线
          muted: '#7e8791', // 辅助文字（暖纸底）
        },
        electric: {
          DEFAULT: '#315cff', // 主行动色（电光蓝）
          hover: '#244be0',
          pale: '#dfe7ff',
          soft: '#eef3ff',
        },
        lime: {
          DEFAULT: '#d9ed83', // 深蓝底上的路径/选中强调
          deep: '#566a1c', // 暖纸底上的对应文字色（≥4.5:1）
          soft: '#eff3dc', // 暖纸底 lime chip 底色
        },
        teal: {
          DEFAULT: '#62c8b4', // 深蓝底上的软前置/辅助强调
          deep: '#2d815e', // 暖纸底文字版
        },
        coral: {
          DEFAULT: '#ee704c', // 小面积状态强调（待复核 / eyebrow 序号）
          deep: '#b36b35', // 暖纸底文字版
        },
        brand: {
          50: '#eef3ff',
          100: '#dfe7ff',
          200: '#b7c8ff',
          300: '#7292ff',
          400: '#4a73ff',
          500: '#4469ff',
          600: '#315cff',
          700: '#244be0',
          800: '#1e3bb0',
          900: '#1a2f80',
        },
        // 难度 1–5（易 → 难）；知识图谱节点按 difficulty 取色（对白底 ≥ 4.5:1）
        difficulty: {
          1: '#059669',
          2: '#65a30d',
          3: '#d97706',
          4: '#ea580c',
          5: '#dc2626',
        },
        // 素材/任务状态；与 api-spec 的 status 枚举一一对应
        status: {
          pending: '#94a3b8',
          parsing: '#3b82f6',
          done: '#10b981',
          partial: '#f59e0b',
          failed: '#ef4444',
        },
        // 语义状态色对（文字 / 浅底），对比度 ≥ 4.5:1（对暖纸/白底）
        success: { DEFAULT: '#166534', soft: '#f0fdf4', line: '#bbf7d0' },
        warning: { DEFAULT: '#92400e', soft: '#fffbeb', line: '#fde68a' },
        danger: { DEFAULT: '#991b1b', soft: '#fef2f2', line: '#fecaca' },
        info: { DEFAULT: '#1e40af', soft: '#eff6ff', line: '#bfdbfe' },
      },
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'PingFang SC',
          'Hiragino Sans GB',
          'Microsoft YaHei',
          'sans-serif',
        ],
        serif: ['Georgia', 'Times New Roman', 'SimSun', 'serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        // 正文 14 / 辅助 13 / 最小标签 12（不得低于 12px 承载必要信息）
        '2xs': ['0.75rem', { lineHeight: '1.125rem', fontWeight: '500' }],
      },
      letterSpacing: {
        widest2: '0.18em',
      },
      borderRadius: {
        // 三档圆角：控件 8 / 卡片与节点 12 / 弹层与面板 16–18
        xl: '0.75rem',
        '2xl': '1rem',
        '3xl': '1.125rem',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        overlay: '0 8px 24px -8px rgb(15 23 42 / 0.18), 0 2px 8px -2px rgb(15 23 42 / 0.08)',
        panel: '0 22px 60px rgb(16 28 46 / 0.10)',
        navy: '0 25px 65px rgb(16 28 46 / 0.22)',
      },
      transitionDuration: {
        // 动效基准：导航/按钮 120ms，内容显现 160ms，抽屉/弹层 220ms
        120: '120ms',
        160: '160ms',
        220: '220ms',
      },
    },
  },
  plugins: [],
}
