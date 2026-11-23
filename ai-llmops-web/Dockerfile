# Node 22 LTS：yarn 4.13 在 Node 24 上有 onCancel 兼容性崩溃（构建环境已实测），22 稳定
FROM node:22-alpine AS builder

WORKDIR /llmops-web

COPY package.json yarn.lock .yarnrc.yml ./

# 启用 Corepack，使用 package.json 中锁定的 yarn 版本
RUN corepack enable && corepack prepare --activate

# yarn v4 安装依赖
# --immutable 对应 v1 的 --frozen-lockfile
# registry 在 .yarnrc.yml 里配置，不在命令行传
RUN --mount=type=cache,target=/root/.cache/yarn \
    yarn install --immutable

COPY . .

ENV VITE_API_PREFIX=/api

RUN yarn build


FROM nginx:alpine AS production
COPY --from=builder /llmops-web/dist /usr/share/nginx/html
COPY --from=builder /llmops-web/docker/nginx/nginx.conf /etc/nginx/conf.d/default.conf

RUN find /usr/share/nginx/html -type d -exec chmod 755 {} \; \
    && find /usr/share/nginx/html -type f -exec chmod 644 {} \;

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]