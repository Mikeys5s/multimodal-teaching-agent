#!/bin/sh
# 容器入口：先跑迁移，再起服务。
#
# ## 为什么把迁移放在入口而不是构建期
#
# 迁移要动的是**运行期的数据库**（挂在 /data 的卷），而镜像构建时那个卷根本不存在。
# 放在入口里，每次启动都会把库升到最新 —— 更新部署时就一条 `docker compose up -d --build`，
# 不需要"记得先跑迁移"这种靠人记住的步骤。
#
# 迁移是幂等的（alembic 会比对 alembic_version），重复执行不会重复建表。

set -e

echo "[entrypoint] 应用数据库迁移 ..."
alembic upgrade head
echo "[entrypoint] 迁移完成"

echo "[entrypoint] 自检数据库 ..."
python -c "
import sys
from sqlalchemy import text

from app.config import settings
from app.db import engine

# ⚠️ 这里**必须**走 app 自己的 engine，不能用裸 sqlite3.connect()。
#    原因：pragma（foreign_keys / WAL / busy_timeout）挂在
#    event.listens_for(engine, 'connect') 上 —— 也就是**每条新连接**都会设一遍。
#    裸连接绕过了那个监听器，读到的会是 SQLite 的默认值 foreign_keys=0，
#    于是在日志里印出一个**假警报**：
#        外键开关 : 0      ← 看起来像外键没生效，其实应用里是好的
#    （这条是本地跑镜像时发现的：日志说 0、接口 /api/health/pragma 说 1，
#      两个数对不上，查下去才确定是自检脚本自己的问题。）
with engine.connect() as conn:
    db = settings.db_file
    tables = sorted(
        r[0]
        for r in conn.execute(
            text(
                \"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\"
            )
        )
    )
    ver = conn.execute(text('SELECT version_num FROM alembic_version')).fetchone()
    fk = conn.execute(text('PRAGMA foreign_keys')).scalar()
    jm = conn.execute(text('PRAGMA journal_mode')).scalar()

print(f'  库文件   : {db}')
print(f'  表数量   : {len(tables)}')
print(f'  迁移版本 : {ver[0] if ver else \"（缺失！）\"}')
print(f'  外键开关 : {fk}   journal_mode: {jm}')

if not ver:
    print('  [!!] 没有 alembic_version 记录 —— 迁移可能没生效', file=sys.stderr)
    sys.exit(1)
if str(fk) != '1':
    print('  [!!] 外键没打开！写入会产生脏数据', file=sys.stderr)
    sys.exit(1)
"

PORT="${APP_PORT:-8000}"
echo "[entrypoint] 启动 uvicorn（0.0.0.0:${PORT}）..."

# --proxy-headers：容器前面若有反代（或将来加域名），让它信任 X-Forwarded-*
# --forwarded-allow-ips：只信容器网络内的来源
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --proxy-headers \
    --forwarded-allow-ips="*"
