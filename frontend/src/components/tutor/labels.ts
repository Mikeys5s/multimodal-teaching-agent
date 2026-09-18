import type { SocraticState, TurnType } from '@/lib/types'

/**
 * 苏格拉底状态机的中文文案与配色。
 * 状态码（S1_PROBE 等）**同时**展示 —— 状态机是本项目的核心差异化，
 * 演示时既要有中文可读性，也要让评委看到状态机真实在跑。
 */

export const SOCRATIC_STATE_LABEL: Record<SocraticState, string> = {
  S0_RETRIEVE: '检索材料',
  S1_PROBE: '反问引导',
  S2_HINT1: '一级提示',
  S3_HINT2: '二级提示',
  S4_EXPLAIN: '直接讲解',
  REFUSE: '超出范围 · 拒答',
  CONFIRM: '确认巩固',
}

export const SOCRATIC_STATE_COLOR: Record<SocraticState, string> = {
  S0_RETRIEVE: '#64748b',
  S1_PROBE: '#2563eb',
  S2_HINT1: '#0ea5e9',
  S3_HINT2: '#8b5cf6',
  S4_EXPLAIN: '#f59e0b',
  REFUSE: '#ef4444',
  CONFIRM: '#10b981',
}

export const TURN_TYPE_LABEL: Record<TurnType, string> = {
  probe: '反问（本轮不给答案）',
  hint1: '一级提示（只给方向）',
  hint2: '二级提示（缩到具体步骤）',
  explain: '直接讲解（已降级）',
  refuse: '拒答（超出材料范围）',
  confirm: '确认巩固',
}

/** 引导阶梯：S1 → S2 → S3 → S4，用于状态机的可视化进度 */
export const SOCRATIC_LADDER: { state: SocraticState; label: string; hint: string }[] = [
  { state: 'S1_PROBE', label: '反问', hint: '只反问，不给答案' },
  { state: 'S2_HINT1', label: '提示 1', hint: '方向性提示' },
  { state: 'S3_HINT2', label: '提示 2', hint: '强提示，仍不给结论' },
  { state: 'S4_EXPLAIN', label: '讲解', hint: '兜底降级，直接讲' },
]

/** 提示级别上限：到 hint_level 2 就是 S3_HINT2（prompt-contracts P7） */
export const MAX_HINT_LEVEL = 2
