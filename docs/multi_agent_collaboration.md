# 多智能体协作说明

当前系统采用以 `TaskRunner` 为中心的角色分工式多智能体流程，不是去中心化的自主协商系统。各角色输出写入共享黑板，便于前端展示、实验记录和复核。

```text
自然语言指令
→ 上下文记忆
→ 本地 RAG 知识检索
→ 语义解析
→ 舒适度分析
→ 能耗审查
→ 任务规划
→ 安全审查
→ 批评审查
→ 虚拟设备执行
→ 环境更新
→ 反馈评估
→ 可选校正
```

## 角色与职责

| 角色 | 主要模块 | 职责 |
| --- | --- | --- |
| 编排器 | `backend/app/experiments/task_runner.py` | 调用各阶段并返回最终响应。 |
| 语义智能体 | `backend/app/agents/semantic_agent.py` | 将用户指令转换为结构化语义 JSON。 |
| 知识智能体 | `backend/app/agents/knowledge_agent.py` | 经 RAG 检索本地文档、配置和任务知识。 |
| 舒适度智能体 | `backend/app/agents/comfort_agent.py` | 在规划前检查目标房间的舒适度缺口。 |
| 能耗智能体 | `backend/app/agents/energy_agent.py` | 识别已开启设备与无人房间的潜在浪费。 |
| 规划智能体 | `backend/app/agents/planning_agent.py` | 由语义和当前状态生成虚拟设备动作计划。 |
| 安全智能体 | `backend/app/agents/safety_agent.py` | 应用健康场景禁开窗、空调/窗户冲突等规则护栏。 |
| 批评智能体 | `backend/app/agents/critic_agent.py` | 审核候选计划并记录问题。 |
| 执行智能体 | `backend/app/agents/execution_agent.py` | 将动作应用到虚拟设备与仿真环境。 |
| 反馈智能体 | `backend/app/agents/feedback_agent.py` | 判断目标是否达到，并提出校正建议。 |
| 大模型客户端 | `backend/app/agents/llm_client.py` | 提供 mock 或真实模型语义解析。 |
| RAG 文档库 | `backend/app/rag/document_store.py` | 索引本地 Markdown、YAML、JSON 源并提供检索。 |

## 运行过程

1. 前端或 API 客户端向 `POST /api/agent/command` 发送指令。
2. `TaskRunner` 读取当前 `SmartHomeState`。
3. 语义智能体提取意图、房间、范围、目标区间和候选设备；知识智能体补充相关上下文。
4. 舒适度、能耗、安全与批评角色形成可检查的审查信息。
5. 规划智能体生成动作，执行智能体更新虚拟设备与环境状态。
6. 反馈智能体评价照明、温湿度、舒适度与明显能耗浪费。
7. 未满足时，编排器最多进行 3 轮校正。

API 响应中的 `agent_output` 包含 `semantic_result`、`planning_result`、`execution_result`、`feedback_result`、`actions`、`final_state` 和 `multi_agent_blackboard`。前端在 `frontend/src/components/AgentOutputPanel.tsx` 中展示相关内容。

## RAG 与实现边界

RAG 默认读取 `docs/*.md`、`backend/app/config/*.yaml` 和 `data/tasks/*.json`。默认离线模式使用确定性词法检索；在 `RAG_RETRIEVAL_MODE=local_embedding` 下，可通过本地 Ollama 嵌入模型执行向量与词法混合检索。两种模式均可追溯来源，缓存不匹配时会重建。

真实大模型目前主要参与语义解析，规划、执行、反馈和校正以可解释的程序逻辑实现。因此，多智能体协作描述的是仿真控制链路；它不等同于真实设备网络的自治控制或安全认证。

新增角色前，应先定义输入、输出、调用位置、失败行为和评价指标。
