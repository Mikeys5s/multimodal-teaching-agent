/**
 * SSE 报文解析纯函数自检 —— 不依赖网络、不依赖后端、不需要测试框架。
 *
 * 运行（frontend 目录下）：
 *   node --experimental-strip-types scripts/check-sse-parse.mjs
 *
 * 覆盖：id 行在 event 行**之前 / 之后**两种顺序、多行 data、注释行与空块、
 *       未知字段（retry）、id 含 NUL、跨 chunk 断包续解析、
 *       readSseSeq 的取值优先级（id 行为权威）与 id/data.seq 不一致检测。
 */
import {
  createSseDecoder,
  parseSseBlock,
  parseSseText,
  readSseSeq,
  readSseSeqInfo,
} from '../src/lib/sse.ts'

let failed = 0
let passed = 0

function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  if (ok) {
    passed += 1
    console.log(`  PASS  ${name}`)
  } else {
    failed += 1
    console.log(`  FAIL  ${name}\n        expected: ${JSON.stringify(expected)}\n        actual:   ${JSON.stringify(actual)}`)
  }
}

/* ---------- ① api-spec §5.2 原文报文（id 行在 event 行之前） ---------- */
const SPEC_SAMPLE = [
  'id: 41',
  'event: retrieved',
  'data: {"seq":41,"kp_ids":["kp_3c81"],"block_ids":["blk_9f2a"],"is_out_of_scope":false}',
  '',
  'id: 42',
  'event: state',
  'data: {"seq":42,"turn_type":"probe","state":"S1_PROBE","hint_level":0}',
  '',
  'id: 43',
  'event: delta',
  'data: {"seq":43,"text":"先想一个问题："}',
  '',
  'id: 44',
  'event: diagnosis',
  'data: {"seq":44,"knowledge_points":[],"stuck_at":null,"next_practice":[]}',
  '',
  'id: 45',
  'event: done',
  'data: {"seq":45,"turn_id":"turn_88","latency_ms":2310,"usage":{"input_tokens":1820,"output_tokens":96}}',
  '',
].join('\n')

console.log('① 报文样例解析（含 id/event/data 三个字段）')
const frames = parseSseText(SPEC_SAMPLE)
check('事件个数', frames.length, 5)
check(
  '事件名顺序',
  frames.map((f) => f.event),
  ['retrieved', 'state', 'delta', 'diagnosis', 'done'],
)
check(
  'id 行取值',
  frames.map((f) => f.id),
  ['41', '42', '43', '44', '45'],
)
check('id 与 data.seq 一致', frames.every((f) => Number(f.id) === JSON.parse(f.data).seq), true)
check('retrieved 负载', JSON.parse(frames[0].data), {
  seq: 41,
  kp_ids: ['kp_3c81'],
  block_ids: ['blk_9f2a'],
  is_out_of_scope: false,
})
check('done 负载 usage', JSON.parse(frames[4].data).usage, { input_tokens: 1820, output_tokens: 96 })

console.log('② id 行在 event 行之后（顺序颠倒也必须能解析）')
const reversed = ['event: delta', 'id: 43', 'data: {"seq":43,"text":"先想一个问题："}'].join('\n')
const reversedFrame = parseSseBlock(reversed)
check('解析结果', reversedFrame, { id: '43', event: 'delta', data: '{"seq":43,"text":"先想一个问题："}' })
check('序号仍取得到', readSseSeq(reversedFrame, JSON.parse(reversedFrame.data)), 43)

console.log('③ 多行 data 按 \\n 拼接')
const multi = ['event: delta', 'data: {"seq":50,', 'data: "text":"换行"}'].join('\n')
const multiFrame = parseSseBlock(multi)
check('拼接后的 data', multiFrame.data, '{"seq":50,\n"text":"换行"}')
check('拼接后是合法 JSON', JSON.parse(multiFrame.data), { seq: 50, text: '换行' })

console.log('④ 注释行、空块、未知字段、id 含 NUL')
check('纯注释块 → null', parseSseBlock(': ping'), null)
check('空块 → null', parseSseBlock(''), null)
const noisy = [
  ': 这是注释，心跳用',
  'retry: 3000',
  'id: 60',
  'event: state',
  'data: {"seq":60,"turn_type":"probe","state":"S1_PROBE","hint_level":0}',
  '',
  ': keep-alive',
  '',
  'event: delta',
  'data:{"seq":61,"text":"无空格 data"}',
  '',
].join('\n')
const noisyFrames = parseSseText(noisy)
check('注释/空块被丢弃，只剩 2 个事件', noisyFrames.length, 2)
check('retry 字段被忽略', noisyFrames[0], {
  id: '60',
  event: 'state',
  data: '{"seq":60,"turn_type":"probe","state":"S1_PROBE","hint_level":0}',
})
check('data: 后无空格也能取值', noisyFrames[1].data, '{"seq":61,"text":"无空格 data"}')
check('id 含 NUL 时按规范忽略', parseSseBlock('id: 6\u00000\nevent: delta\ndata: {"seq":62}'), {
  id: null,
  event: 'delta',
  data: '{"seq":62}',
})
check('块内只有 data 无 event / id', parseSseBlock('data: {"seq":63}'), {
  id: null,
  event: '',
  data: '{"seq":63}',
})

console.log('⑤ 跨 chunk 断包（半截 id 行、半截分隔符都要能续上）')
const decoder = createSseDecoder()
const chunks = [
  'id: 4',
  '1\nevent: retrie',
  'ved\ndata: {"seq":41,"kp_ids":["kp_3c81"],"block_ids":["blk_9f2a"],"is_out_of_scope":false}\n\nid: 42\nevent: state\nda',
  'ta: {"seq":42,"turn_type":"probe","state":"S1_PROBE","hint_level":0}',
]
const streamed = []
for (const chunk of chunks) streamed.push(...decoder.push(chunk))
streamed.push(...decoder.flush())
check('流式解析结果与整段解析逐字节一致', streamed, parseSseText(SPEC_SAMPLE).slice(0, 2))
check('流式事件名', streamed.map((f) => f.event), ['retrieved', 'state'])
check('流式 id', streamed.map((f) => f.id), ['41', '42'])

console.log('⑥ 末块没有结尾空行（flush 兜底）')
const tailDecoder = createSseDecoder()
const partial = tailDecoder.push('id: 7\nevent: done\ndata: {"seq":7,"turn_id":"turn_1","latency_ms":10,"usage":null}')
check('未 flush 时无事件', partial.length, 0)
check('flush 后拿到 done', tailDecoder.flush().map((f) => f.event), ['done'])

console.log('⑦ readSseSeq：id 行为权威（Last-Event-ID 取 id 行的值），data.seq 仅兜底')
check('id 行优先于 data.seq', readSseSeq({ id: '99', event: 'delta', data: '{}' }, { seq: 41 }), 99)
check('两者一致时结果不变', readSseSeq({ id: '41', event: 'delta', data: '{}' }, { seq: 41 }), 41)
check('无 id 行 → 回退 data.seq', readSseSeq({ id: null, event: 'delta', data: '{}' }, { seq: 41 }), 41)
check('无 data.seq → 用 id', readSseSeq({ id: '42', event: 'delta', data: '{}' }, {}), 42)
check('两者都没有 → null', readSseSeq({ id: null, event: 'delta', data: '{}' }, {}), null)
check('非数字 id 不误取', readSseSeq({ id: 'abc', event: 'delta', data: '{}' }, null), null)

console.log('⑦′ id 与 data.seq 不一致检测（api-spec §5.2 硬约定）')
check('都不等 → mismatch=true，且仍按 id 推进', readSseSeqInfo({ id: '43', event: 'delta', data: '{}' }, { seq: 44 }), {
  seq: 43,
  source: 'id',
  mismatch: true,
  idSeq: 43,
  dataSeq: 44,
})
check('一致 → mismatch=false', readSseSeqInfo({ id: '43', event: 'delta', data: '{}' }, { seq: 43 }).mismatch, false)
check('只有 id → 不算不一致', readSseSeqInfo({ id: '43', event: 'delta', data: '{}' }, {}).mismatch, false)
check('只有 data.seq → 不算不一致', readSseSeqInfo({ id: null, event: 'delta', data: '{}' }, { seq: 43 }).mismatch, false)
check(
  '契约样例报文全程无 mismatch',
  parseSseText(SPEC_SAMPLE).some(
    (f) => readSseSeqInfo(f, JSON.parse(f.data)).mismatch,
  ),
  false,
)

console.log(`\n结果：${passed} 项通过，${failed} 项失败`)
process.exit(failed === 0 ? 0 : 1)
