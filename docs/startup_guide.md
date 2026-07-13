# 启动指南

本指南默认使用 Docker Compose 启动，也保留本地前后端开发方式。

## 前置条件

- 推荐路径：已安装并启动 Docker Desktop。
- 本地开发路径：Python 3.11+、Node.js 18+ 和 npm。

## 一键 Docker 启动

在项目根目录执行：

```powershell
.\start.ps1
```

或双击 `start.bat`。脚本会在缺失时由示例文件创建 `deploy/.env` 与 `deploy/backend.env`，运行 `docker compose up -d --build`，等待 `http://localhost/health` 就绪，然后打开：

```text
http://localhost
```

Docker Desktop 必须处于运行状态。

## 本地后端开发

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

检查：`http://localhost:8000/health`

## 本地前端开发

```powershell
cd frontend
npm install
npm run dev
```

访问：`http://localhost:5173`

## 手动 Docker 命令

```powershell
Copy-Item deploy\backend.env.example deploy\backend.env
Copy-Item deploy\.env.example deploy\.env
cd deploy
docker compose up -d --build
```

停止服务：

```powershell
cd deploy
docker compose down
```

旧的热更新脚本仍可用于排障：

```powershell
.\scripts\start_backend.ps1
.\scripts\start_frontend.ps1
```

在 VS Code 中按 `Ctrl+Shift+B`，选择“启动智能家居仿真实验平台”。

## 环境变量与模型模式

Docker 使用 `deploy/backend.env`；本地非 Docker 开发使用 `backend/.env`。默认建议使用 `LLM_MODE=mock`，获得确定性的本地语义基线；仅在已配置兼容端点、模型名和凭据时使用 `LLM_MODE=real`。

若验证 Docker 服务中的本地 Ollama，实验命令应显式指定 `--env-file deploy\backend.env`，避免主机环境与服务环境不一致。运行前将不可变 Ollama 模型摘要记录到 `REAL_LLM_MODEL_REVISION`；没有版本绑定的真实模型运行不能作为版本特定性能证据。

## 验证命令

```powershell
.\backend\.venv\Scripts\python.exe scripts\verify_real_llm.py
.\backend\.venv\Scripts\python.exe scripts\run_batch_experiments.py --limit 5
.\backend\.venv\Scripts\python.exe scripts\run_reproduction_experiments.py --limit 3 --real-mode mock
.\backend\.venv\Scripts\python.exe scripts\run_quality_loop.py
```

日志与结果写入 `data/logs/`、`data/results/`；除 `.gitkeep` 外通常不会提交。

## 常见问题

- Docker 引擎未运行：启动 Docker Desktop，确认其就绪后重新运行 `start.bat` 或 `start.ps1`。
- 镜像拉取超时：在 `deploy/.env` 设置 `DOCKER_HUB_PREFIX=m.daocloud.io/docker.io/library/` 后重试。
- 80 端口占用：在 `deploy/.env` 将 `FRONTEND_PORT` 改为例如 `8080`。
- Docker 前端不能加载状态：先确认 `http://localhost/health` 可访问、后端容器健康。
- 本地前端不能加载状态：确认后端 8000 端口运行，且 `VITE_API_BASE_URL` 配置正确。
- 真实模型验证失败：检查环境文件、端点 URL、模型名、模型服务、密钥和返回格式；不要在日志或仓库中输出真实密钥。
- 没有实验输出：确认 `data/tasks/` 中的任务 JSON 存在，且命令使用了正确的环境文件。
