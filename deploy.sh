#!/bin/bash
set -e

echo "===== [1/5] 清理旧进程 ====="
sudo pkill -f uvicorn || true
sleep 1

echo "===== [2/5] 修复 WARP 配置为 proxy 模式 ====="
# 先断开 WARP（如果已连接）
warp-cli --accept-tos disconnect 2>/dev/null || true
echo "[4/7] Configuring Cloudflare WARP for YouTube bypass..."
warp-cli --accept-tos registration new || echo "WARP already registered."
warp-cli --accept-tos mode proxy
warp-cli --accept-tos proxy port 40000
warp-cli --accept-tos connect
sleep 3
# 打印 WARP 状态
echo "WARP 状态:"
warp-cli --accept-tos status 2>/dev/null || echo "WARP 未安装或无法获取状态"

echo "===== [3/5] 安装 Python 依赖 ====="
cd /home/ubuntu/VideoSnap
/home/ubuntu/.local/bin/uv sync 2>&1 || true

echo "===== [4/5] 放行 UFW 8000 端口 ====="
sudo ufw allow 8000/tcp 2>/dev/null || true

echo "===== [5/5] 启动 uvicorn ====="
cd /home/ubuntu/VideoSnap
nohup /home/ubuntu/.local/bin/uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000 > /home/ubuntu/VideoSnap/app.log 2>&1 &
sleep 3

# 验证进程是否启动
if pgrep -f "uvicorn main:app" > /dev/null; then
    echo "✅ uvicorn 启动成功！PID: $(pgrep -f 'uvicorn main:app')"
else
    echo "❌ uvicorn 启动失败，日志如下："
    cat /home/ubuntu/VideoSnap/app.log
    exit 1
fi

# 验证本地访问
echo "===== 验证本地访问 ====="
RESULT=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/)
echo "首页状态码: $RESULT"
CSS_RESULT=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/static/style.css)
echo "CSS 状态码: $CSS_RESULT"

echo "===== 部署完成 ====="
