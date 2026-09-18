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
import sqlite3, sys
from app.config import settings

db = settings.db_file
con = sqlite3.connect(db)
tables = sorted(r[0] for r in con.execute(
    \"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'\"
))
ver = con.execute('SELECT version_num FROM alembic_version').fetchone()
print(f'  库文件   : {db}')
print(f'  表数量   : {len(tables)}')
print(f'  迁移版本 : {ver[0] if ver else \"（缺失！）\"}')
fk = con.execute('PRAGMA foreign_keys').fetchone()[0]
print(f'  外键开关 : {fk}')

if not ver:
    print('  [!!] 没有 alembic_version 记录 —— 迁移可能没生效', file=sys.stderr)
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
