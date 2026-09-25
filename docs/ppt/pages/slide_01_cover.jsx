<Slide style={{
    width: '1280px', height: '720px', background: '#FFFFFF',
    padding: '56px 80px', flexDirection: 'column', justifyContent: 'space-between',
}}>
    {/* 右上角装饰：抽象网格（L3 级，不影响安全区） */}
    <Box style={{
        position: 'absolute', top: 0, right: 0, width: 520, height: 300,
        background: 'linear-gradient(135deg, rgba(59,130,246,0.10) 0%, rgba(6,182,212,0.02) 100%)',
        zIndex: 0,
    }} />

    <Box style={{ flexDirection: 'row', alignItems: 'center', gap: 16, marginTop: 8 }}>
        <Box style={{ width: 44, height: 44, borderRadius: 10, background: '#0F172A', alignItems: 'center', justifyContent: 'center' }}>
            <Text style={{ fontSize: 20, fontWeight: 'bold', color: '#FFFFFF' }}>析</Text>
        </Box>
        <Text style={{ fontSize: 20, color: '#64748B', letterSpacing: 1 }}>粤港澳大湾区 AI Coding 创新大赛 · 方向一</Text>
    </Box>

    <Box style={{ flexDirection: 'column', gap: 24, zIndex: 1 }}>
        <Text style={{ fontSize: 88, fontWeight: 'bold', color: '#0F172A', lineHeight: 1.15, letterSpacing: -1 }}>
            析知 XiZhi
        </Text>
        <Text style={{ fontSize: 30, color: '#3B82F6', fontWeight: 'bold', lineHeight: 1.4 }}>
            多模态教学智能体
        </Text>
        <Box style={{ width: 120, height: 5, background: '#06B6D4', borderRadius: 3, marginTop: 4 }} />
        <Text style={{ fontSize: 24, color: '#1A1A1A', lineHeight: 1.7, maxWidth: 880 }}>
            让教学材料变成<Text style={{ fontSize: 24, fontWeight: 'bold', color: '#0F172A' }}>可查询、可溯源、能引导自学</Text>的结构化知识体
            <br />
            <Text style={{ fontSize: 22, color: '#64748B' }}>图文素材智能解析 · 知识点结构化抽取 · 交互式答疑辅导</Text>
        </Text>
    </Box>

    <Box style={{ flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <Box style={{ flexDirection: 'row', gap: 40 }}>
            <Box style={{ flexDirection: 'column', gap: 6 }}>
                <Text style={{ fontSize: 36, fontWeight: 'bold', color: '#06B6D4', fontFamily: 'JetBrains Mono, monospace' }}>3</Text>
                <Text style={{ fontSize: 14, color: '#64748B' }}>阶段管线</Text>
            </Box>
            <Box style={{ flexDirection: 'column', gap: 6 }}>
                <Text style={{ fontSize: 36, fontWeight: 'bold', color: '#06B6D4', fontFamily: 'JetBrains Mono, monospace' }}>5</Text>
                <Text style={{ fontSize: 14, color: '#64748B' }}>验收项全通过</Text>
            </Box>
            <Box style={{ flexDirection: 'column', gap: 6 }}>
                <Text style={{ fontSize: 36, fontWeight: 'bold', color: '#06B6D4', fontFamily: 'JetBrains Mono, monospace' }}>0</Text>
                <Text style={{ fontSize: 14, color: '#64748B' }}>依赖图环数</Text>
            </Box>
        </Box>
        <Text style={{ fontSize: 14, color: '#64748B' }}>8 人时 / 天 × 10 天 · 三人团队</Text>
    </Box>
</Slide>
