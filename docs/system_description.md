# 系统说明

本项目是用于自然语言控制与环境反馈研究的本地智能家居数字孪生仿真平台。

> 系统模拟灯光、空调、窗帘、风扇、窗户、传感器、房间、天气、舒适度与能耗模型；不直接连接真实全屋家居设备。

**RAG 检索关键词：** devices air conditioner（设备、空调）。

## 系统范围

系统在虚拟空间中模拟房间、设备、室外条件、舒适度和能耗。它适合原型验证与可重复实验，不应直接作为生产自动化逻辑、建筑设计、工程验收或健康安全决策。

## 主要模块

- `backend/app/main.py`：FastAPI 应用与 API 路由。
- `backend/app/simulation/`：设备、照明、热、湿度、天气、能耗和舒适度模型。
- `backend/app/agents/`：语义解析、规划、执行、反馈、上下文和多智能体协作。
- `backend/app/rag/`：本地知识索引、词法/本地嵌入混合检索和缓存校验。
- `backend/app/experiments/`：编排、日志、批量运行与评估工具。
- `frontend/src/`：React 界面、API 客户端、状态类型、控制面板和 3D 场景。
- `deploy/`：Docker Compose、Nginx 和部署环境变量模板。
- `scripts/`：启动、验证、评估和实验入口。

## 环境与设备模型

每个虚拟房间包含照度、温度、湿度、人员占用、活动场景和设备状态。虚拟设备包括灯光、窗帘、空调、风扇、窗户和传感器；室外状态包括天气、时间、照度、太阳辐射、温湿度。在线天气不可用时，后端使用本地生成曲线。

## 智能体闭环

`TaskRunner` 是核心编排器。它先完成语义解析与本地知识检索，再结合舒适度、能耗、安全与批评审查生成计划，随后执行虚拟设备动作并进行反馈评估。反馈不满足时最多进行 3 轮校正，以保证运行可预测、日志可审计。

大模型主要用于语义解析；规划、执行、反馈和校正仍以可解释的确定性程序逻辑为主。因此，`mock` 模式可作为稳定基线，`real` 模式则需要单独记录模型版本、环境与原始实验产物。

系统还提供后端常驻的持续自治模式。它不依赖浏览器定时器，能够周期性读取虚拟传感器和人员占用状态，在个性化阈值被触发时自动生成任务，并在执行后由反思智能体形成结构化经验。人员进入暗房间时可先经过一个仅控制当前房间灯光、可记录且受手动覆盖约束的有界 reflex；其余自治动作全部进入 `TaskRunner` 的完整规划和安全路径。成功后冷却、连续失败停机、300 秒手动覆盖、两阶段安全停止、生活仿真互斥和禁止并行工作线程构成运行保护。用户画像、结构化长期属性、反馈、反思和情境经验按稳定的本地住户空间写入私有记忆；详细契约与边界见 [autonomous_personalization.md](autonomous_personalization.md)，状态所有权见 [runtime_control_contract.md](runtime_control_contract.md)。

## 数据、指标与复现

后端可在 `data/results/` 下写入 CSV、JSON 和 Markdown 报告。常见指标包括意图/房间识别、选择设备、动作数量、完成状态、校正次数、响应时延、能耗与舒适度分数。

确定性研究运行时会记录种子、初始状态哈希、语义输入指纹、规划/执行事件、工具调用、状态差异和 JSONL 日志；可通过 `scripts/replay_research_log.py` 回放。架构和回放契约见 [research_runtime_architecture.md](research_runtime_architecture.md)。

## 研究边界

环境、能耗、照明、湿度与舒适度是轻量化近似模型。它们支持受控的软件比较，却不替代真实建筑物理、已校准传感器、现场安全系统或生产级设备集成。相关阈值的使用范围见 [national_standards_basis.md](national_standards_basis.md)，真实设备的验收条件见 [field_validation_protocol.md](field_validation_protocol.md)。

本地质量门禁可运行：

```powershell
.\backend\.venv\Scripts\python.exe scripts\run_quality_loop.py
```

它会把验证证据与后续建议写入 `data/results/quality/`，不会自动修改源码、部署或发布。
