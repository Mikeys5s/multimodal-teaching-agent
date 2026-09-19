/**
 * SSE 流式客户端（Stage 3 · D8）。
 *
 * ★ 为什么不用 `EventSource`：`POST /api/qa/sessions/{id}/ask` 是 **POST + JSON body**，
 *   而 `EventSource` 只支持 GET、也不能自定义请求头（因此无法带 `Last-Event-ID`）。
 *   所以这里用 `fetch` + `ReadableStream` 手写行解析。
 *
 * ★ 与 `types.ts` §5.2 的三条硬约定一一对应：
 *   1. 每个事件都带 `id:` 行且与 `data.seq` 一致。**续推游标以 `id:` 为权威** ——
 *      `Last-Event-ID` 按 SSE 规范携带的就是 `id:` 行的值，而 `id:` 由服务端自己写出、
 *      正是它比对续推位置时使用的游标；`data.seq` 只是同值的便利副本（缺失时兜底）。
 *      两者不一致即后端违约（见 `readSseSeqInfo().mismatch`）→ 发 `SEQ_MISMATCH` 告警，
 *      **不静默吞掉**（`id:` 错位会让续推错位，必须让人看见）。
 *   2. `id:` 必须在 `event:` 之前 → 解析按行处理，**不依赖字段在块内的出现顺序**
 *      （两种顺序都能解析出正确结果）；但发送重连请求时一定用最后收到的 seq。
 *   3. `seq` 会话内单调递增、跨轮次不重置 → `streamAsk` 接收 `lastEventId`、
 *      返回本轮 `lastSeq`，由调用方在**会话级别**持有（只有新建会话才清零）。
 *      ★ 这是 seq 的**唯一**推进来源：调用方不要再自己维护一份，见 `StreamAskResult`。
 *
 * ★ 事件顺序固定：`retrieved` → `state` → `delta`* → `diagnosis` → `done`。
 *   调用方拿到 `retrieved` 就应当**先渲染溯源卡片**，再渲染 `delta` 文本。
 *
 * ★ 本文件**没有任何运行时静态导入**（`API_BASE` / `ApiError` 在 `streamAsk` 内
 *   动态 `import('./api')`，复用 `api.ts` 里那一套 base，不硬编码）——
 *   这样纯解析函数能被 `node --experimental-strip-types` 直接加载做离线自检，
 *   见 `frontend/scripts/check-sse-parse.mjs`。
 */

import type { ApiEnvelope, SseDelta, SseDiagnosis, SseDone, SseRetrieved, SseState } from './types'

/* ------------------------------------------------------------------ *
 * 一、纯解析层（无副作用，可离线自检）
 * ------------------------------------------------------------------ */

/** 事件块分隔符（空行）。CRLF / LF / CR 三种换行都可能出现。 */
const BLOCK_SEP_SOURCE = '\\r\\n\\r\\n|\\n\\n|\\r\\r'
/** 行分隔符 */
const LINE_SEP_RE = /\r\n|\n|\r/

export type SseEventName = 'retrieved' | 'state' | 'delta' | 'diagnosis' | 'done'

const KNOWN_EVENTS: readonly string[] = ['retrieved', 'state', 'delta', 'diagnosis', 'done']

export interface SseFrame {
  /** `id:` 行的值；没有该行则为 null。本项目里与 `data.seq` 一致。 */
  id: string | null
  /** `event:` 行的值；没有该行则为空串（SSE 规范里等价于 message，本项目不会出现） */
  event: string
  /** `data:` 行内容；多行按 SSE 规范用 `\n` 拼接 */
  data: string
}

/**
 * 解析**单个事件块**（块内不含分隔空行）。
 *
 * 容忍：任意字段顺序（`id:` 在 `event:` 前后都行）、多行 `data:`、
 *       以 `:` 开头的注释行、未知字段（如 `retry`、`id` 含 NUL 按规范忽略）。
 * 返回 null 表示整块是注释 / 空块 / 不含任何已知字段。
 */
export function parseSseBlock(block: string): SseFrame | null {
  if (!block) return null

  let id: string | null = null
  let event = ''
  const dataLines: string[] = []
  let sawField = false

  for (const line of block.split(LINE_SEP_RE)) {
    if (line === '') continue
    // 注释行（心跳常用 `: ping`）
    if (line.startsWith(':')) continue

    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    // 规范：冒号后若紧跟一个空格，去掉这一个空格（只去一个）
    if (value.startsWith(' ')) value = value.slice(1)

    switch (field) {
      case 'id':
        // 规范：含 NUL 字符的 id 应被忽略
        if (!value.includes('\u0000')) id = value
        sawField = true
        break
      case 'event':
        event = value
        sawField = true
        break
      case 'data':
        dataLines.push(value)
        sawField = true
        break
      default:
        // 未知字段按规范忽略（例如 retry）
        break
    }
  }

  if (!sawField) return null
  return { id, event, data: dataLines.join('\n') }
}

/** 纯函数：把**一段完整报文**切成事件列表（自检与调试用） */
export function parseSseText(text: string): SseFrame[] {
  const frames: SseFrame[] = []
  for (const block of text.split(new RegExp(BLOCK_SEP_SOURCE, 'g'))) {
    const frame = parseSseBlock(block)
    if (frame) frames.push(frame)
  }
  return frames
}

export interface SseDecoder {
  /** 喂入一段（可能是半截的）文本，返回其中**已经完整**的事件 */
  push(chunk: string): SseFrame[]
  /** 流已结束：把缓冲区里没有结尾空行的残块也解析出来 */
  flush(): SseFrame[]
}

/**
 * 增量解码器：跨 chunk 保留残块，保证一个事件的字节被拆到两次 `read()` 也能正确解析。
 */
export function createSseDecoder(): SseDecoder {
  let buffer = ''

  const drain = (final: boolean): SseFrame[] => {
    const frames: SseFrame[] = []
    const re = new RegExp(BLOCK_SEP_SOURCE, 'g')
    let last = 0
    let match: RegExpExecArray | null
    while ((match = re.exec(buffer)) !== null) {
      const frame = parseSseBlock(buffer.slice(last, match.index))
      if (frame) frames.push(frame)
      last = match.index + match[0].length
    }
    buffer = buffer.slice(last)
    if (final && buffer.trim() !== '') {
      const frame = parseSseBlock(buffer)
      if (frame) frames.push(frame)
      buffer = ''
    }
    return frames
  }

  return {
    push: (chunk: string) => {
      buffer += chunk
      return drain(false)
    },
    flush: () => drain(true),
  }
}

/** 本项目里 `id:` 行固定是十进制序号；非数字（或缺失）一律视为「没给 id」 */
function parseIdSeq(id: string | null): number | null {
  return id !== null && /^\d+$/.test(id) ? Number(id) : null
}

/** 事件序号 + 它的来源 + 一致性信息（见 `readSseSeqInfo`） */
export interface SseSeqInfo {
  /** 用于推进 `lastSeq` / 作为 `Last-Event-ID` 的序号 */
  seq: number | null
  /** 序号的来源：`id:` 行为权威来源，`data.seq` 仅在缺 `id:` 时兜底 */
  source: 'id' | 'data' | null
  /** `id:` 与 `data.seq` **都存在且不相等** —— 后端违反 api-spec §5.2 的硬约定 */
  mismatch: boolean
  idSeq: number | null
  dataSeq: number | null
}

/**
 * 取事件序号及其一致性信息。
 *
 * ★ 优先级 **`id:` > `data.seq`**：`Last-Event-ID` 按 SSE 规范携带的是 `id:` 行的值，
 *   而 `id:` 由服务端生成，是它比对续推位置时真正使用的游标；`data.seq` 只是同值副本。
 *   契约保证两者一致，正常链路上两种取法结果相同；**一旦不一致（`mismatch`），
 *   能让续推对上的只有 `id:`** —— 此时仍然按 `id:` 推进，并把违约报出去（不静默）。
 */
export function readSseSeqInfo(frame: SseFrame, payload: unknown): SseSeqInfo {
  const idSeq = parseIdSeq(frame.id)

  let dataSeq: number | null = null
  if (payload && typeof payload === 'object') {
    const seq = (payload as { seq?: unknown }).seq
    if (typeof seq === 'number' && Number.isFinite(seq)) dataSeq = seq
  }

  const mismatch = idSeq !== null && dataSeq !== null && idSeq !== dataSeq
  const seq = idSeq ?? dataSeq

  return {
    seq,
    source: idSeq !== null ? 'id' : dataSeq !== null ? 'data' : null,
    mismatch,
    idSeq,
    dataSeq,
  }
}

/** 只取序号（`readSseSeqInfo` 的便捷用法） */
export function readSseSeq(frame: SseFrame, payload: unknown): number | null {
  return readSseSeqInfo(frame, payload).seq
}

/* ------------------------------------------------------------------ *
 * 二、网络层：streamAsk
 * ------------------------------------------------------------------ */

/** 协议层告警（目前只有「`id:` 与 `data.seq` 不一致」）—— 不阻断本轮回答，但必须可见 */
export interface SseProtocolWarning {
  code: 'SEQ_MISMATCH'
  /** 可直接展示 / 上报的中文说明 */
  message: string
  /** 触发告警的事件名 */
  event: SseEventName
  idSeq: number | null
  dataSeq: number | null
}

/** 流中断时，抛出的错误对象上会附带**已经推进到的 seq**（供调用方保留续推游标） */
export interface SsePartialSeq {
  lastSeq: number | null
}

export interface SseHandlers {
  onRetrieved?: (event: SseRetrieved) => void
  onState?: (event: SseState) => void
  onDelta?: (event: SseDelta) => void
  onDiagnosis?: (event: SseDiagnosis) => void
  onDone?: (event: SseDone) => void
  /**
   * 通用分发器：任何已识别事件都会先经过这里（用来做埋点、统计等横切逻辑）。
   * `seq` 为 null 表示报文里既没有 `id:` 也没有 `data.seq`。
   * ⚠️ **不要在这里推进 seq** —— `streamAsk` 的返回值就是唯一来源（见 `StreamAskResult`）。
   */
  onEvent?: (name: SseEventName, payload: unknown, seq: number | null) => void
  /** 收到协议层违约（如 `SEQ_MISMATCH`）时回调一次，便于上报或界面提示 */
  onProtocolWarning?: (warning: SseProtocolWarning) => void
}

export interface StreamAskParams {
  sessionId: string
  question: string
  /**
   * 断线续推：上一轮**最后收到的 seq**（跨轮次保留，不要每轮清零）。
   * 传了就会带 `Last-Event-ID` 请求头，服务端从该 seq 之后续推。
   */
  lastEventId?: number | null
  signal?: AbortSignal
  handlers?: SseHandlers
}

export interface StreamAskResult {
  /**
   * 本轮最后收到的 seq —— 调用方应保留到会话结束，并**只用这一个来源**：
   * 下一轮把它作为 `lastEventId` 传回（`Last-Event-ID` 断线续推）。
   * 流中途出错时这个值在抛出的错误上（`SsePartialSeq.lastSeq`）。
   */
  lastSeq: number | null
}

type ApiModule = typeof import('./api')

/** 把后端 `{ok:false,error:{...}}` 包封（或非 JSON 文本）转成可展示的中文错误 */
function envelopeError(
  ApiErrorCtor: ApiModule['ApiError'],
  text: string,
  httpStatus: number,
  fallback: string,
): Error {
  try {
    const env = JSON.parse(text) as ApiEnvelope<unknown>
    if (env && env.ok === false && env.error) {
      return new ApiErrorCtor(env.error.code, env.error.message, {
        detail: env.error.detail,
        requestId: env.request_id,
        httpStatus,
      })
    }
  } catch {
    /* 不是 JSON —— 落到下面的兜底文案 */
  }
  return new ApiErrorCtor(httpStatus >= 500 ? 'INTERNAL' : 'BAD_RESPONSE', fallback, { httpStatus })
}

/**
 * 发起一轮提问并以 SSE 流式接收回复。
 *
 * 错误一律是可展示的中文（与 `api.ts` 一致）：
 *   - 后端未启动 / 网络失败 → `NETWORK_ERROR`
 *   - 非 2xx 或返回 JSON 错误包封 → 沿用后端 `error.message`
 *   - 2xx 但不是 `text/event-stream` → `BAD_RESPONSE`
 * 用户主动中断会抛出 `AbortError`（原样抛出，交给调用方识别）。
 */
export async function streamAsk(params: StreamAskParams): Promise<StreamAskResult> {
  const { sessionId, question, lastEventId, signal, handlers = {} } = params

  // 动态引入：复用 api.ts 的 base，同时让本模块保持「零运行时静态导入」以便离线自检
  const { API_BASE, ApiError } = await import('./api')

  const url = `${API_BASE}/qa/sessions/${encodeURIComponent(sessionId)}/ask`
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (typeof lastEventId === 'number' && Number.isFinite(lastEventId)) {
    headers['Last-Event-ID'] = String(lastEventId)
  }

  let res: Response
  try {
    res = await fetch(url, { method: 'POST', headers, body: JSON.stringify({ question }), signal })
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') throw err
    throw new ApiError('NETWORK_ERROR', '无法连接后端服务，请确认后端已启动后重试。')
  }

  const contentType = (res.headers.get('Content-Type') ?? '').toLowerCase()

  // ① 非 2xx，或「成功」却返回 JSON（契约漂移）—— 两种都按包封解析
  if (!res.ok || contentType.includes('application/json')) {
    const text = await res.text().catch(() => '')
    throw envelopeError(
      ApiError,
      text,
      res.status,
      `答疑请求失败（HTTP ${res.status}），请稍后重试。`,
    )
  }

  // ② 200 但不是事件流 —— 明确报错，不要静默把内容当流读
  if (!contentType.includes('text/event-stream')) {
    const text = await res.text().catch(() => '')
    throw envelopeError(
      ApiError,
      text,
      res.status,
      `答疑接口返回了非事件流响应（Content-Type: ${contentType || '未知'}），无法解析。`,
    )
  }

  if (!res.body) {
    throw new ApiError('BAD_RESPONSE', '当前浏览器不支持流式响应读取（ReadableStream 不可用）。', {
      httpStatus: res.status,
    })
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const sse = createSseDecoder()

  let lastSeq: number | null =
    typeof lastEventId === 'number' && Number.isFinite(lastEventId) ? lastEventId : null
  let sawEvent = false
  let rawPrefix = ''
  /** 同一条告警在一次流里只报一次，避免后端系统性错位时刷屏 */
  const warned = new Set<string>()

  const dispatch = (frame: SseFrame): void => {
    const name = frame.event
    if (!KNOWN_EVENTS.includes(name)) return // 无 event 行 / 未知事件：忽略，保证前向兼容

    let payload: unknown = null
    if (frame.data !== '') {
      try {
        payload = JSON.parse(frame.data)
      } catch {
        throw new ApiError('BAD_RESPONSE', `流式响应的 ${name} 事件不是合法 JSON，本轮回答已中断。`)
      }
    }
    if (!payload || typeof payload !== 'object') {
      throw new ApiError('BAD_RESPONSE', `流式响应的 ${name} 事件负载格式不正确，本轮回答已中断。`)
    }

    const eventName = name as SseEventName
    const seqInfo = readSseSeqInfo(frame, payload)
    const seq = seqInfo.seq
    if (seq !== null) lastSeq = lastSeq === null ? seq : Math.max(lastSeq, seq)
    sawEvent = true

    // 后端违约：id: 与 data.seq 不一致 → 显式告警（协议规定 Last-Event-ID 取 id: 行的值，
    // 错位会让断线续推错位；不静默吞掉，否则这类 bug 只能靠人工读报文才发现）
    if (seqInfo.mismatch && !warned.has('SEQ_MISMATCH')) {
      warned.add('SEQ_MISMATCH')
      const warning: SseProtocolWarning = {
        code: 'SEQ_MISMATCH',
        message: `SSE 报文中 id: 行（${seqInfo.idSeq}）与 data.seq（${seqInfo.dataSeq}）不一致，违反 api-spec §5.2；已按 id: 续推。`,
        event: eventName,
        idSeq: seqInfo.idSeq,
        dataSeq: seqInfo.dataSeq,
      }
      console.warn(`[xizhi/sse] ${warning.message}`)
      handlers.onProtocolWarning?.(warning)
    }

    handlers.onEvent?.(eventName, payload, seq)
    if (eventName === 'retrieved') handlers.onRetrieved?.(payload as SseRetrieved)
    else if (eventName === 'state') handlers.onState?.(payload as SseState)
    else if (eventName === 'delta') handlers.onDelta?.(payload as SseDelta)
    else if (eventName === 'diagnosis') handlers.onDiagnosis?.(payload as SseDiagnosis)
    else handlers.onDone?.(payload as SseDone)
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      if (!value) continue
      const chunk = decoder.decode(value, { stream: true })
      if (rawPrefix.length < 512) rawPrefix = (rawPrefix + chunk).slice(0, 512)
      for (const frame of sse.push(chunk)) dispatch(frame)
    }
    for (const frame of sse.flush()) dispatch(frame)
  } catch (err) {
    const passthrough = (err as Error)?.name === 'AbortError' || err instanceof ApiError
    const out =
      passthrough
        ? err
        : new ApiError('NETWORK_ERROR', '流式连接中断，请重试（可凭上一轮序号续推）。')
    // 把**已经推进到的 seq** 挂到错误对象上：调用方据此保住续推游标，
    // 否则中断前的这半轮白跑、重试只能从上一轮的游标重新开始
    ;(out as Error & SsePartialSeq).lastSeq = lastSeq
    throw out
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* 中断时可能仍有 pending read，releaseLock 会抛 —— 忽略，避免盖掉真正的错误 */
    }
  }

  // ③ 服务端标了 event-stream 却回了个 JSON 包封（常见于反向代理把错误包封透传）
  if (!sawEvent && rawPrefix.trimStart().startsWith('{')) {
    throw envelopeError(ApiError, rawPrefix, res.status, '答疑接口未返回事件流，收到的是 JSON 响应。')
  }

  return { lastSeq }
}
