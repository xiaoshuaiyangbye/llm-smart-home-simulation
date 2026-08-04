# 大模型智能家居数字孪生仿真平台

这是一个可本地运行、可复现实验的自治型个性化智能家居数字孪生平台，用于研究持续环境感知、后端自主决策、自然语言设备控制、RAG 检索增强、多智能体协作、虚拟设备执行、执行后反思与长期用户适应。

## 项目定位与结论边界

本项目验证的是**软件仿真闭环**：用户指令进入智能体流程后，系统完成语义解析、规划、虚拟设备控制、环境演化与反馈校正。它适用于课程设计、科研原型、算法对比与可复现实验。

项目不直接接入真实全屋设备，因此不能仅凭本仓库的测试或仿真结果，宣称真实设备控制安全性、实际节能效果或建筑工程合规性。

与本软件平台配套的照明研究已具备实体实验基础：真实办公实验环境中的照度传感、控制器/PWM 调光、LED 驱动与反馈闭环可作为**照明子系统**的独立硬件验证证据。该证据不能自动外推为本项目所有虚拟设备均完成实体部署。详细验收口径见 [docs/field_validation_protocol.md](docs/field_validation_protocol.md)。

## 主要能力

- 后端：Python + FastAPI，管理仿真状态、虚拟设备、环境模型、智能体编排和 CSV 日志导出。
- 前端：React + TypeScript + Vite，提供 2D/延迟加载 3D 智能家居控制界面。
- 闭环控制：语义解析、任务规划、动作执行、环境更新、反馈评估，最多执行 3 轮校正。
- 多智能体：知识检索、舒适度、能耗、安全、批评审查、执行与反馈结果写入可检查的黑板（blackboard）。
- 后端自治：不依赖浏览器的常驻感知循环，具备重复触发冷却、连续失败停机、运行互斥、状态查询与显式启停。
- 私有记忆：按稳定的本地住户空间保存结构化属性、偏好、反馈、反思与情境经验；显式反馈可确认或纠正最近一次反思。
- 反思智能体：每次交互或自治控制后生成独立、可追踪的 Reflection Agent 阶段，并把经验写回后续决策上下文。
- RAG：支持确定性词法检索，或使用本地 Ollama 嵌入模型的向量与词法混合检索；索引带内容指纹和校验和缓存。
- 大模型：支持稳定可复现的 `mock` 模式，以及兼容 OpenAI API 的 `real` 模式；默认本地配置可使用 Ollama 的 `qwen3:8b`。
- 实验：提供批量任务、复现实验、个性化消融、生命周期仿真、质量门禁和报告生成脚本。

自治运行、私有知识和反思学习的接口、保护机制与证据边界见 [docs/autonomous_personalization.md](docs/autonomous_personalization.md)；交互控制、持续自治、生活仿真与研究运行时的状态所有权和互斥关系见 [docs/runtime_control_contract.md](docs/runtime_control_contract.md)。

大论文《基于大语言模型智能体的智能家居系统研究》的研究问题、对照、指标、当前证据、创新性边界和投稿前缺口集中见 [docs/thesis_argument_chain.md](docs/thesis_argument_chain.md)；机器可读主张矩阵可用 `scripts/validate_thesis_claims.py` 校验。该校验会区分“论证结构完整”和“证据已达到投稿要求”。

## 目录结构

```text
backend/    FastAPI、仿真模型、智能体、RAG、测试与实验逻辑
frontend/   React/Vite 前端、状态面板与 3D 场景
deploy/     Docker Compose、Nginx 和部署环境变量模板
scripts/    启动、验证、评估和实验脚本
data/       任务定义；生成的日志与结果默认不提交
docs/       中文系统说明、实验边界、运行与部署文档
```

## 快速启动

### Windows 一键启动（推荐）

确保 Docker Desktop 已启动后，在项目根目录执行：

```powershell
.\start.ps1
```

也可以双击 `start.bat`。启动器会在缺失时从模板创建 `deploy/.env` 和 `deploy/backend.env`；当 `LLM_MODE=real` 时，它还会启动并等待本机 Ollama 就绪。随后构建并启动 Docker Compose 服务，等待健康检查后打开：

```text
http://localhost
```

完整说明见 [docs/startup_guide.md](docs/startup_guide.md)。

### 本地开发：后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：`http://localhost:8000/health`

### 本地开发：前端

```powershell
cd frontend
npm install
npm run dev
```

访问：`http://localhost:5173`

### 手动 Docker Compose

```powershell
Copy-Item deploy\backend.env.example deploy\backend.env
Copy-Item deploy\.env.example deploy\.env
cd deploy
docker compose up -d --build
```

Docker 模式下，前端容器默认监听 80 端口，并将 `/api/*` 与 `/health` 反向代理到后端。镜像拉取超时时，可在 `deploy/.env` 配置：

```env
DOCKER_HUB_PREFIX=m.daocloud.io/docker.io/library/
```

## 大模型与本地 Ollama

Docker 读取 `deploy/backend.env`；不使用 Docker 的本地开发读取 `backend/.env`。请勿提交真实密钥。

```env
APP_ENV=local
LLM_MODE=mock
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
REAL_LLM_API_KEY=
REAL_LLM_BASE_URL=
REAL_LLM_MODEL=
REAL_LLM_MODEL_REVISION=
REAL_LLM_TIMEOUT_SECONDS=12
REAL_LLM_MAX_TOKENS=600
REAL_LLM_STREAM=true
```

- `LLM_MODE=mock`：确定性本地语义解析，适合演示、测试与基线实验。
- `LLM_MODE=real`：调用兼容 OpenAI Chat Completions 的真实模型服务。

如需真实本地 Ollama，请复制 `backend/.env.local.example` 为被 Git 忽略的 `backend/.env.local`。默认配置使用 `qwen3:8b` 解析语义、`qwen3-embedding:0.6b` 建立本地嵌入索引。请将 Ollama 返回的模型摘要写入 `REAL_LLM_MODEL_REVISION`，使实验结果能够绑定到不可变模型版本。

本地嵌入索引默认保存在 `.runtime/rag_index.json`。其中包含源文件指纹与索引校验和；源文件、配置或缓存损坏发生变化时会安全重建。检查 RAG：

```powershell
.\backend\.venv\Scripts\python.exe scripts\inspect_rag.py --reindex
.\backend\.venv\Scripts\python.exe scripts\evaluate_rag.py --min-recall 1.0
```

验证真实模型连通性：

```powershell
.\backend\.venv\Scripts\python.exe scripts\verify_real_llm.py
```

## 常用实验命令

```powershell
# 确定性研究运行时演示与回放
.\backend\.venv\Scripts\python.exe scripts\run_research_demo.py
.\backend\.venv\Scripts\python.exe scripts\replay_research_log.py data\logs\research_demo.jsonl

# 小批量任务与复现实验
.\backend\.venv\Scripts\python.exe scripts\run_batch_experiments.py --limit 5
.\backend\.venv\Scripts\python.exe scripts\run_reproduction_experiments.py --limit 3 --real-mode mock

# 个性化多目标消融实验
.\backend\.venv\Scripts\python.exe scripts\run_personalization_experiments.py

# RQ1 guarded/unguarded 快照提交隔离对照
.\backend\.venv\Scripts\python.exe scripts\run_snapshot_commit_experiment.py --repeats 100

# 生成两套不含参考答案的独立语义标注任务包
.\backend\.venv\Scripts\python.exe scripts\prepare_semantic_review_packets.py

# 本地质量门禁
.\backend\.venv\Scripts\python.exe scripts\run_quality_loop.py

# 论文论证链结构与当前证据检查
.\backend\.venv\Scripts\python.exe scripts\validate_thesis_claims.py --require-generated-evidence

# 已启动 Docker 后，以独立 QA 住户空间串联验证正式 API（结果写入 data/results/quality/）
.\backend\.venv\Scripts\python.exe scripts\smoke_live_api.py --base-url http://localhost
```

生成的日志和报告位于 `data/logs/`、`data/results/` 与 `output/`，默认不会提交到 Git。真实模型实验应单独保存模型版本、环境配置指纹、任务集版本与原始结果；一次成功请求不是模型准确率、时延或并发能力的总体结论。

## 真实设备结论验收

若要将某项结论表述为真实设备、现场安全或实际节能结果，必须复制并填写 `data/field_validation/field_validation_evidence.example.json`，为原始产物建立 SHA-256 清单，再执行：

```powershell
$env:ARTIFACT_SIGNING_KEY = '<从仓库外的密钥管理系统注入>'
.\backend\.venv\Scripts\python.exe scripts\verify_artifact_integrity.py create <原始产物目录> --require-signature
.\backend\.venv\Scripts\python.exe scripts\validate_field_validation_evidence.py <完成的证据文件.json>
```

验收要求包括隔离环境、设备/固件清单、已验证的回滚和急停、校准传感器、基线策略、原始日志与完整产物清单。校验器只检查证据完整性，不会生成现场数据，也不会把仿真结果升级为实体实验结论。

## API 概览

- `GET /health`：后端健康检查。
- `GET /api/state`：获取当前仿真状态。
- `POST /api/agent/command`：执行自然语言的语义—规划—执行—反馈流程。
- `GET /api/rag/sources`：列出已索引的 RAG 源文件。
- `POST /api/rag/reindex`：重建 RAG 索引。
- `POST /api/rag/query`：检索本地知识片段。
- `POST /api/state/reset`：重置当前仿真会话状态。
- `GET /api/logs/export`：导出 CSV 日志。

## 质量与安全说明

公开部署时，在 `deploy/backend.env` 中设置强 `API_AUTH_TOKEN`、显式 `BACKEND_CORS_ORIGINS` 和独立的 `PRIVATE_MEMORY_ENCRYPTION_KEY`。浏览器通过 HTTP-only、严格 SameSite 的 Cookie 保存经验证的令牌；API 客户端也可使用 `X-API-Key`。`X-Simulation-Session` 仅用于隔离不同浏览器会话的仿真状态，不是身份认证。Docker 将 `data/private_memory/` 挂载为持久卷，容器重建不会自动丢失住户记忆。

Fernet 密钥必须在仓库外生成并进入密钥管理流程；禁止提交真实密钥。部署前运行以下 fail-closed 门禁，输出只报告检查结果，不打印密钥：

```powershell
.\backend\.venv\Scripts\python.exe scripts\validate_deployment_config.py deploy\backend.env
```

运行时可通过 `GET /api/system/readiness` 查看认证、加密、持久化和自治快照提交状态。该接口是软件可观测性，不是隐私合规或真实设备安全证明。

仓库的持续验证包括后端测试和 Ruff、前端 Vitest/生产构建、浏览器端到端测试、RAG 评测、依赖一致性与高危 npm 审计。改进闭环与停止规则见 [docs/loop_engineering.md](docs/loop_engineering.md)，历史证据见 [docs/improvement_backlog.md](docs/improvement_backlog.md)。
