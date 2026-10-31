# =====================================================================
# agent · 前端镜像（默认前端构建 + Nginx 托管）
#
# 构建上下文必须是仓库根目录（agent/）：
#   docker build -f deploy/frontend/Dockerfile -t agent-web:1.1.0 .
#
# 构建对象：仓库中唯一的前端实现 frontend/web/vue-element-plus
#
# 两段式构建：
#   builder: node:22-alpine  → npm ci → npm run build → /build/dist
#   runtime: nginx:1.27-alpine → 仅包含构建产物 + 我们自己的 nginx 配置
#
# 对外只暴露 80 端口：静态资源由 Nginx 直出，/api 反向代理到 backend:8000
# =====================================================================

# ---------------- 阶段 1：构建 ----------------
FROM node:22-alpine AS builder

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /build

# 先只拷贝依赖清单，最大化利用 Docker 层缓存
COPY frontend/web/vue-element-plus/package.json frontend/web/vue-element-plus/package-lock.json ./
RUN npm ci --no-audit --no-fund --registry="${NPM_REGISTRY}"

# 再拷贝源码构建
COPY frontend/web/vue-element-plus/ ./
RUN npm run build \
    && ls -lh dist \
    && du -sh dist

# ---------------- 阶段 2：运行 ----------------
FROM nginx:1.27-alpine AS runtime

# ---------- Nginx 运行身份说明（务必读）----------
# 本镜像**不是**整容器非 root：
#   - 官方 nginx:alpine 的 **master 进程以 root 启动**（需要绑定 80 端口）；
#   - **worker 进程以 nginx 用户运行**（见 deploy/nginx/nginx.conf 的 `user nginx;`）。
# 下面只是把 worker 需要写入的缓存 / 日志目录属主准备好，**并非**整容器非 root。
#
# 若要改成**整容器非 root**，必须**四处同步**改，缺一即启动失败：
#   1) deploy/nginx/nginx.conf：listen 80 → listen 8080（<1024 端口需特权），
#      pid /var/run/nginx.pid → /tmp/nginx.pid（nginx 用户不可写 /var/run）；
#   2) deploy/frontend/Dockerfile：追加 `USER nginx`（并保证 /var/cache/nginx、/var/log/nginx 可写）；
#   3) docker-compose.yml：端口映射 `...:80` → `...:8080`（宿主侧仍是 ${HOST_HTTP_PORT:-8080}）；
#   4) docker-compose.yml：web 的 healthcheck 改 http://127.0.0.1:8080/nginx-healthz。
# 详见 deploy/README.md §4.6。
RUN mkdir -p /var/cache/nginx/client_temp /var/log/nginx \
    && chown -R nginx:nginx /var/cache/nginx /var/log/nginx

# Nginx 配置
COPY deploy/nginx/nginx.conf            /etc/nginx/nginx.conf
COPY deploy/nginx/conf.d/agent.conf /etc/nginx/conf.d/default.conf

# 前端构建产物（由 builder 阶段产出）
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

STOPSIGNAL SIGQUIT

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
