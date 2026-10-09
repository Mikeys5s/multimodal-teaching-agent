/**
 * 知识点标题与重复组的**唯一文案出口**（决赛期 P3 任务 1、2）。
 *
 * 为什么单独开一个文件而不是在各组件里就地判断：
 *   ① **措辞纪律要集中**：重复组只做「标注」、不做物理去重，
 *      所以界面**永远不能出现「已去重」**。散落在 6 个组件里的字符串没法审计。
 *   ② **字段尚未全部落地**：可读标题（`display_title` / `raw_name`）后端还没给，
 *      重复组三件套（`is_duplicate` / `duplicate_of` / `duplicate_group_size`）线上已经有了。
 *      把「有就用、没有就回落」收在一处，后端补齐时组件一行都不用改。
 *   ③ **溯源不能丢**：拿到可读标题之后，原始句片段必须还能被看到（收进 tooltip）。
 *
 * 口径来源：Gitee Issue IKJVBE（【P3】决赛任务）。
 */

/** 标题三件套的最小结构 —— 只要满足这个形状就能用，不用绑死具体实体类型 */
export interface TitleFields {
  name?: string | null
  display_title?: string | null
  raw_name?: string | null
}

/** 重复组三件套的最小结构 */
export interface DupFields {
  is_duplicate?: boolean | null
  duplicate_of?: string | null
  duplicate_group_size?: number | null
}

const clean = (value: string | null | undefined): string => (value ?? '').trim()

/**
 * 原始名（抽取出来的句片段）。
 * `raw_name` 存在时优先用它；否则退回 `name` —— 现阶段线上只有 `name`。
 */
export function kpRawName(kp: TitleFields): string {
  return clean(kp.raw_name) || clean(kp.name)
}

/**
 * **界面上应该显示的名字**。
 * 有可读标题用可读标题，没有就还原样显示（宁可丑，也不编一个）。
 */
export function kpDisplayTitle(kp: TitleFields): string {
  return clean(kp.display_title) || kpRawName(kp) || '（未命名知识点）'
}

/** 是否已经拿到**不同于原名**的可读标题 */
export function hasReadableTitle(kp: TitleFields): boolean {
  const display = clean(kp.display_title)
  return display.length > 0 && display !== kpRawName(kp)
}

/**
 * 是否该把原名作为悬停提示暴露出来。
 * 只有「拿到了可读标题、且与原名不同」时才需要 —— 否则 tooltip 会重复显示同一个字符串。
 */
export function shouldExposeRawName(kp: TitleFields): boolean {
  const raw = kpRawName(kp)
  return hasReadableTitle(kp) && raw.length > 0 && raw !== kpDisplayTitle(kp)
}

/** `title` 属性用：拿到可读标题时标注原名，便于溯源（悬停可见） */
export function kpTitleAttr(kp: TitleFields): string | undefined {
  return shouldExposeRawName(kp) ? `原名：${kpRawName(kp)}` : undefined
}

/**
 * 组内点数；**不需要提示时返回 `null`**。
 *
 * 返回 `null` 的两种情况：
 * - 后端没给这个字段（老数据 / 图谱节点接口当前就不带它）
 * - `size <= 1`（独立知识点，没有重复可讲）
 *
 * ⚠️ 不要把它当成 `0` 处理 —— `0` 会被 `?? 1` 之类的写法吃掉，导致「独立点也显示提示」。
 */
export function dupGroupSize(kp: DupFields): number | null {
  const size = kp.duplicate_group_size
  if (typeof size !== 'number' || !Number.isFinite(size) || size <= 1) return null
  return size
}

/**
 * 重复组提示文案（详情面板用整句）。
 *
 * 判据来自 Issue：「显示类似『本知识点在材料中出现 4 处，已合并显示』」。
 * ⚠️ **绝不能写成「已去重」** —— 我们是标注、不是去重，写成「已去重」就是假的。
 * 副本条目再补一句「本条是副本」，让「为什么两条内容一样」有明确解释。
 */
export function dupNotice(kp: DupFields): string | null {
  const size = dupGroupSize(kp)
  if (size === null) return null
  const base = `本知识点在材料中出现 ${size} 处，已合并显示`
  return kp.is_duplicate ? `${base}；本条是副本，与代表点内容一致。` : `${base}。`
}

/**
 * 重复组的**短标签**（列表 / 节点角标用，放不下整句的地方）。
 * 同样避开「去重」字样。
 */
export function dupBadgeLabel(kp: DupFields): string | null {
  const size = dupGroupSize(kp)
  if (size === null) return null
  return `共 ${size} 处`
}
