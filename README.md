# VideoSnap

> 极夜光晕风格 · 全平台免部署无界视频中枢抽取器

VideoSnap 是一款高度优化的全平台短视频极速提取网络应用。只需一个唯一的入口，通过智能的后端辨识和强悍的混合云验证代理（包含前端 TLS 隧道穿透），在彻底剔除了繁琐登录验证的同时，实现了极致的响应速度。

## ✨ 核心特性

- **极致毛玻璃拟态 UI**：V5 终极版，界面仅保留悬浮搜索胶囊，极简径向星空背景。适配移动端及现代浏览器。
- **Cloudflare + Nginx 二级网路代理**：结合 Cloudflare 边缘加速与 Nginx 本地转发，保障生产环境稳定。
- **One-Input 智能全网分发**：无感提取 YouTube、Instagram、X (Twitter)、Facebook 及 TikTok 视频。
- **速率限制 (Rate Limiting)**：内置每人每天 5 次搜索的限流策略，通过 `CF-Connecting-IP` 精准识别，保护服务器资源。
- **零缓冲流式加速**：应用 `X-Accel-Buffering: no` 及 Nginx 缓冲禁用法，实现大文件点对点极致透传，减少等待延迟。

## 🚀 启动与部署

本项目使用 `uv` 进行统一管理。

### 本地开发
```bash
uv sync
uv run python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 生产部署 (Oracle Cloud / Ubuntu)
1. **安装 Nginx** 并配置反向代理：
   ```nginx
   server {
       listen 80;
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_buffering off;
           proxy_set_header CF-Connecting-IP $http_cf_connecting_ip;
       }
   }
   ```
2. **连接 Cloudflare** 并设置为“Flexible (灵活)” SSL 模式。
3. **环境变量**：确保安装了 `static-ffmpeg` 依赖或系统中已存在 ffmpeg。
4. **YouTube 后备**：若在数据中心 IP 被拦截，项目会自动切换至 `cobalt.tools` 提供的后备 API 方案。

---

> 该项目仅供学习交流使用，请勿用于任何非法用途。
