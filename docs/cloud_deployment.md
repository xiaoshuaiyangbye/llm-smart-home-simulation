# 云端部署指南

项目可以通过现有 PowerShell 脚本本地运行，也可以使用 Docker Compose 部署到云服务器。

## 相关文件

```text
backend/Dockerfile          后端 API 镜像
frontend/Dockerfile         前端构建与 Nginx 镜像
deploy/docker-compose.yml   服务编排
deploy/nginx/default.conf   静态前端与 API 反向代理
deploy/backend.env.example  后端运行环境变量模板
deploy/.env.example         Compose 级环境变量模板
```

## 首次部署

在服务器安装 Docker 与 Docker Compose 后，先复制环境变量模板：

```bash
cp deploy/backend.env.example deploy/backend.env
cp deploy/.env.example deploy/.env
```

启用真实大模型前，编辑服务器上的 `deploy/backend.env`。密钥只应保存在服务器环境文件或专用密钥管理服务中，不得提交到 Git。

如 Docker Hub 拉取镜像出现超时或 `failed to fetch oauth token`，可在 `deploy/.env` 设置镜像前缀：

```env
DOCKER_HUB_PREFIX=m.daocloud.io/docker.io/library/
```

启动服务：

```bash
cd deploy
docker compose up -d --build
```

默认访问地址：

```text
http://<服务器 IP>/
```

前端容器负责 React 静态文件，并将 `/api/*`、`/health` 转发给后端；默认只需对外开放前端端口。

## 更新与观察

拉取新代码后重新构建：

```bash
cd deploy
docker compose up -d --build
docker compose ps
```

生成日志和报告挂载在：

```text
data/logs/
data/results/
```

部署完成后应至少检查 `/health`，并按研究需要保存当前镜像版本、环境变量模板版本和实验产物清单。

## 生产边界

- 在真实模型端点与密钥完成配置前，保持 `LLM_MODE=mock`。
- 公开访问时必须配置强 `API_AUTH_TOKEN`，并在反向代理层使用 HTTPS、域名绑定和证书续期。
- 若前后端通过内置 Nginx 使用同域访问，保持 `VITE_API_BASE_URL` 为空；若浏览器访问独立后端域名，则显式配置 `VITE_API_BASE_URL` 与 `BACKEND_CORS_ORIGINS`。
- 云端部署只是软件服务发布，不构成真实家居设备控制、安全或节能效果的验证。
