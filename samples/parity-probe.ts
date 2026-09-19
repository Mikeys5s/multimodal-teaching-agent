/**
 * 契约比对工具的**故意写错**夹具。
 *
 * ⚠️ 这个文件里的写法**全是错的/刁钻的** —— 它不是产品代码，不要照抄。
 * 它的唯一用途是喂给 `scripts/check-api-parity.py --selftest`，
 * 验证工具在**该报的时候会报、不该报的时候不报**。
 *
 * ## 为什么需要它
 *
 * 今天我写的检查工具出过 4 次问题（漏检报成功、结论写死、误报、跨盘测试）。
 * **一个从没被喂过「应该失败」样例的检查，等于没有检查。**
 *
 * 下面 4 条，前 2 条是我今天**真踩过**的 bug，后 2 条是正常的正确写法。
 */

const api = {
  // ① 模板字符串 `${id}` 写法 —— 归一化必须处理它。
  //    我曾在重写时漏掉 `${...}`，只处理 `{...}`，
  //    于是报了「14 处路径对不上」的**假问题**。
  getMaterial: (id: string) => request<Material>(`/materials/${id}`),

  // ② 这一条**没有** method —— 必须是默认 GET。
  //    我曾让"往后看 3 行"去找 method，结果它把**下一条**的 POST 借了过来，
  //    报出「方法对不上」的假问题。
  listMaterials: () => request<Paginated<Material>>('/materials'),

  // ③ 显式方法写在**下一行**（正常写法）—— 必须被正确读到，
  //    而且**不能**泄给下一条调用。
  extractKnowledge: (body: ExtractRequest) =>
    request<ExtractAccepted>('/extract/knowledge', {
      method: 'POST',
      body,
    }),

  // ④ 方法写错（后端 /api/health 只有 GET）—— **必须被抓到**。
  wrongMethod: () => request<Health>('/health', { method: 'POST' }),

  // ⑤ 路径根本不存在 —— **必须被抓到**。
  wrongPath: () => request<unknown>('/definitely-not-a-real-endpoint'),
};
