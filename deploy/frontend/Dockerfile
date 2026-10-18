# =====================================================================
# Agent Platform · 前端镜像（默认前端构建 + Nginx 托管）
#
# 构建上下文必须是仓库根目录（agent-platform/）：
#   docker build -f deploy/frontend/Dockerfile -t agent-platform-web:1.1.0 .
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

# 非 root 运行所需的缓存目录
RUN mkdir -p /var/cache/nginx/client_temp /var/log/nginx \
    && chown -R nginx:nginx /var/cache/nginx /var/log/nginx

# Nginx 配置
COPY deploy/nginx/nginx.conf            /etc/nginx/nginx.conf
COPY deploy/nginx/conf.d/agent-platform.conf /etc/nginx/conf.d/default.conf

# 前端构建产物（由 builder 阶段产出）
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

STOPSIGNAL SIGQUIT

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
