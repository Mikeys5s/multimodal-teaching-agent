/** 学习路径目标面板（Learning Atlas 深蓝制图材质，装饰性路线图为纯视觉，不代表真实数据） */
export function PathHero({ targetName, chapterLabel }: { targetName: string; chapterLabel?: string }) {
  // 纯数字章节号（如 '299'）加 CH. 前缀，避免看起来像一串无意义数字；真实章名原样展示
  const chapterText = chapterLabel
    ? /^\d+$/.test(chapterLabel)
      ? `CH. ${chapterLabel}`
      : chapterLabel
    : undefined
  return (
    <section className="atlas-navy-panel !rounded-2xl grid gap-5 px-6 py-6 sm:px-7 lg:grid-cols-[0.92fr_1.08fr] lg:items-center">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 right-[-40px] h-[390px] w-[390px] rounded-full border border-teal/30 shadow-[0_0_0_35px_rgba(98,200,180,0.04),0_0_0_75px_rgba(98,200,180,0.035)]"
      />
      <div className="relative z-10">
        <div className="atlas-eyebrow !text-[#a8b3c0]">
          TARGET CONCEPT{chapterText ? ` / ${chapterText}` : ''}
        </div>
        <h2 className="mt-2.5 text-2xl font-bold tracking-[-0.03em]">{targetName}</h2>
        <p className="mt-2 max-w-[410px] text-xs leading-relaxed text-[#b3bdc9]">
          一条好路径不只是步骤列表。每一步都说明为什么先学它、它来自哪里，以及接下来如何连接到目标。
        </p>
        <div className="mt-4 flex items-center gap-3">
          <span
            aria-hidden
            className="grid h-9 w-9 place-items-center rounded-full border border-lime/45 font-serif text-base italic text-lime"
          >
            ●
          </span>
          <span>
            <span className="block text-xs font-semibold">当前目标 / {targetName}</span>
            {chapterText && (
              <span className="mt-0.5 block text-[10px] text-[#9eabb8]">来源：{chapterText}</span>
            )}
          </span>
        </div>
      </div>

      {/* 装饰性小路线图（纯视觉氛围，不代表真实路径） */}
      <svg viewBox="0 0 440 170" fill="none" aria-hidden className="relative z-10 hidden h-[150px] w-full lg:block">
        <path
          d="M20 120C91 118 72 55 152 63s64 76 127 63 77-46 141-83"
          stroke="#d9ed83"
          strokeWidth="2"
          className="atlas-draw"
        />
        <path d="M152 63c34-56 83-46 119-36M279 126c21 42 57 47 94 25" stroke="#8295ac" strokeWidth="1" strokeDasharray="3 6" />
        <g fill="#101c2e" stroke="#f2efe7" strokeWidth="1.4">
          <circle cx="20" cy="120" r="8" />
          <circle cx="152" cy="63" r="9" />
          <circle cx="279" cy="126" r="9" />
          <circle cx="420" cy="43" r="11" />
        </g>
        <circle cx="420" cy="43" r="4" fill="#d9ed83" />
        <g fill="#d5dee8" fontSize="8">
          <text x="7" y="145">LAYER</text>
          <text x="128" y="91">PROTOCOL</text>
          <text x="254" y="152">WINDOW</text>
          <text x="386" y="24" fill="#d9ed83">TARGET</text>
        </g>
      </svg>
    </section>
  )
}
