/** @type {import('tailwindcss').Config} */
// 析知 XiZhi 设计 token 集中定义
// - brand：唯一主行动色（品牌连续性，api-spec 不约束视觉，但语义色不可改义）
// - difficulty：难度 1–5（SPEC §5.2 F2.7 节点颜色映射难度）
// - status：素材/任务状态，与 api-spec §3.2 status 枚举一一对应
// - 语义色（success/warning/danger/info）：只承载状态含义，必须配文字/图标，不靠颜色单独传达
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
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
        // 语义状态色对（文字 / 浅底），对比度 ≥ 4.5:1（对白底）
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
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        // 正文 14 / 辅助 13 / 最小标签 12（不得低于 12px 承载必要信息）
        '2xs': ['0.75rem', { lineHeight: '1.125rem', fontWeight: '500' }],
      },
      borderRadius: {
        // 三档圆角：控件 8 / 卡片与节点 12 / 弹层 16
        xl: '0.75rem',
        '2xl': '1rem',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        overlay: '0 8px 24px -8px rgb(15 23 42 / 0.18), 0 2px 8px -2px rgb(15 23 42 / 0.08)',
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
