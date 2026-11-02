# 五阶段证据完善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依次修复已证实的指令保持、时间记账和结果契约缺口，补真实模型挑战及上下文贡献对照，保持论文结论可追溯。

**Architecture:** 每阶段先建立可推翻修复的测试，再作最小实现并记录独立验证。历史冻结产物不修改，新口径使用新schema/结果目录；人工审查保持独立未完成状态。

**Tech Stack:** Python、pytest、Pydantic、TaskRunner、本地Ollama、现有React/Vite页面。

## Global Constraints

- 用户已授权五项工作并要求先计划后执行；逐项验收，不把整张计划当一次无限扩展的改动。
- 保留全部既有dirty修改；编辑前保存涉及文件快照；不提交、推送、部署、删除数据或修改密钥。
- 后端使用 `backend\.venv\Scripts\python.exe`；前端命令从 `frontend/` 运行。
- 不重写历史实验或把mock/组件结果称为真实模型/真实设备证据。
- 本机未安装上列superpowers执行子技能，按本计划在当前会话逐项执行，不因此增加确认步骤。
- 真实独立标注不能由代理代替；相关材料与拒绝不完整证据的校验可完成，外部审查需真实人员提交。
- 各阶段是独立可验证修复。并行仅限不相交的只读调查；共享实现按依赖顺序推进。

## Task 1: 保持显式设备约束

**Files:** Modify `backend/app/agents/explicit_control.py`; Test `backend/tests/test_explicit_control.py`。检查 `backend/app/simulation/device_model.py` 已有的 `turn_on` / `set_mode` 接口，优先复用而不扩大设备模型。

**Interfaces:** 保持 `preserve_explicit_control(result: dict, command: str) -> dict`、`explicit_actions(semantic: dict, state) -> list[dict]`、`explicit_feedback(semantic: dict, state, revision_round: int) -> dict`。契约新增可选 `mode`、范围及分句约束，模型错误仍返回错误；只处理可明确识别的单设备范围，冲突不可猜测执行。

- [ ] 1a 制热：先增加真实TaskRunner失败测试，设冷模式初态、提交制热27度，断言最终 `mode == 'heat'` 且 `setpoint_c == 27`。再解析明确制热/制冷，使用设备支持的动作设置模式；没有指定模式时保留现有有效模式。
- [ ] 1b 否定：测试“不要关闭客厅灯，把亮度调到40%”得到开灯40%，单独“不要关闭”保持初态；分句提取禁止操作，不能把整个命令吞掉。
- [ ] 1c 区间：测试“空调设在24到26度”保留 `[24,26]`，可确定性选择中点25；反向区间、越界及相互冲突目标返回错误，不静默取末值。反馈检查范围而非伪造单点要求。

```python
response = runner.run_agent_command(AgentCommandRequest(user_command='把客厅空调制热到27度'))
ac = next(d for d in response.final_state.devices if d.entity_id == 'ac.living_room_main')
assert response.success and ac.mode == 'heat' and ac.setpoint_c == 27
```

- [ ] 运行 `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_explicit_control.py -q`，保留修复前失败与修复后通过日志；检查 `/health`、`/api/agent/health`，适用时浏览器确认制热结果；保存最小smoke，不重跑7200条作为本项前置条件。
- [ ] 写backlog、roadmap、claims及 `W:\大论文\论文规划\实验完善进展-20261017.md`，标明确定性保护不是模型准确率提升。

## Task 2: 统一时钟、物理与能耗

**Files:** Modify `backend/app/simulation/environment.py`, `backend/app/simulation/energy_model.py`, `backend/app/experiments/episode_benchmark.py`; Test `backend/tests/test_simulation_accounting.py`。检查 `backend/app/simulation/life_simulation.py` 和季节实验的额外基线累计，避免双记。

**Interfaces:** `step(minutes=0, refresh_realtime=False)`不推进；负时长拒绝；动作及设置环境默认瞬时，只重算代数指标。`step(minutes=n)`以一分钟子步统一推进时钟、热湿和能耗。显式batch `dt_minutes>0` 若保留，则必须调用同一个推进器；天气快照不重置已推进的分钟。

- [ ] 保存红色证据：动作前后时钟、温度、湿度和累计能耗完全不变（照度/即时功率可变）；step(0)不推进；30分钟与30次1分钟的状态/能耗一致；跨午夜一致。

```python
a, b = SmartHomeEnvironment(initial), SmartHomeEnvironment(initial)
a.step(30, refresh_realtime=False)
for _ in range(30):
    b.step(1, refresh_realtime=False)
assert a.get_state(False).model_dump() == b.get_state(False).model_dump()
```

- [ ] 实现统一推进，明确能量为一分钟离散积分而非现实校准值；清理重复累计；新E1记录输出时钟差、积分方式及schema版本。
- [ ] 运行环境、生活模拟、历史/季节实验、E1、决策回放相关测试。新目录生成E1 smoke；验证方法间总仿真分钟相等，历史演示的冻结数据保留。
- [ ] 记录旧结果与新测量口径不可直接合并。

## Task 3: 扩展结果契约和覆盖度

**Files:** Create `data/research/e1_episode_tasks_v3.json`; Modify `backend/app/experiments/episode_benchmark.py`, `scripts/run_e1_episode_benchmark.py`; Test `backend/tests/test_e1_episode_benchmark.py`。

**Interfaces:** `check_outcome(state, checks)`保留，另加轨迹契约函数 `check_trajectory(states: list, contract: dict) -> dict`；返回可观察要求通过、覆盖度、未测要求与 `complete_intent_verified`，不让部分谓词通过等同完整意图。

- [ ] 为学习/睡眠/观影加入明确的仿真照度或设备目标、温度、禁止副作用与逐分钟维持窗口；噪声和眩光未建模，单列 `unmeasured_requirements`，禁止猜测物理量。
- [ ] 反例测试：仅温度合格而阅读照度不足应失败；窗口中一次违反应失败；缺实体应失败；存在未测要求时不能宣称完整意图验证。

```python
result = check_trajectory([before, during_violation, after], contract)
assert result['observable_success'] is False
assert result['complete_intent_verified'] is False
```

- [ ] CLI明确选择v3任务文件并冻结；跑24基础任务的4方法smoke，输出逐项失败原因和覆盖度。保留v2输入与7200历史结果。

## Task 4: 真实模型挑战与人工审查交付

**Files:** Create `data/tasks/explicit_control_challenge_v1.json`, `scripts/run_explicit_control_challenge.py`, `backend/tests/test_explicit_control_challenge.py`; reuse `scripts/prepare_semantic_review_packets.py`。

**Interfaces:** challenge任务包含稳定 `task_id`、`user_command`、`category`、初态、设备谓词、预期拒绝与标签来源；运行器先记录 `LLMClient.parse_command` 原始输出，再记录相同输出经过确定性保护后的系统行为，分开计分；`--mode mock|real --repeat-count 3 --output-dir PATH`，真实模式不得回退mock冒充成功。

- [ ] 冻结修复代码hash后构造24个挑战，覆盖热/冷、范围、复合否定、边界、冲突、多房间上下文；开发者撰写标签明确标记非独立审查。记录冻结时间；对已用于开发的案例标为regression，对首次评测案例标为developer challenge，不宣称训练集污染已排除。
- [ ] 测试缺模式、解析错误、执行拒绝与命中率分母，确保失败进入结果，不丢弃。3重复只分析稳定性，主性能每任务取预定第1重复。

```python
assert summary['primary_record_count'] == summary['task_count']
assert summary['independent_human_review_complete'] is False
```

- [ ] 固定本地模型digest，mock先smoke再有限real完整挑战；保存原始响应、来源、参数、错误、hash和对照。若服务不可用，保存明确失败证据并停在真实结果缺口，不生成成功数字。
- [ ] 生成两份盲审包及裁决说明；空白审查应被现有validator拒绝。RQ5保持blocked，直到真实独立人员的材料到达。

## Task 5: memory/RAG 实际输入与贡献

**Files:** Inspect/modify `backend/app/agents/llm_client.py`, `backend/app/experiments/task_runner.py`, `backend/app/research/personalization.py`; Create `scripts/run_context_contribution.py`, `backend/tests/test_context_contribution.py`。

**Interfaces:** 保持LLMClient公开接口；compact context新增受限、来源明确的检索数据与确认经验字段。未确认经验不入模型prompt，原始外部文本作为数据，不能升级为系统指令；显式目标和安全限制仍在现有执行层约束。

- [ ] 用捕获实际HTTP请求payload的测试确认现状：RAG字段是否被白名单删除，confirmed_experience是否到达解析/规划。测试开关改变的是模型看到的输入，而非只改trace。
- [ ] 最小修复丢失的上下文，限制长度和字段，保留source/provenance；测试未确认经验不可见、明确27度不被偏好覆盖、恶意知识不能绕过确定性安全。

```python
assert 'rag_context' in captured_prompt_with_context
assert 'rag_context' not in captured_prompt_without_context
assert unconfirmed_marker not in captured_prompt_with_context
```

- [ ] 冻结相同任务、初态、模型digest与解码设置，运行 `memory on/off × RAG on/off` 的有限配对对照；逐任务保存输入hash、原始输出、最终动作、通过率和延迟。零增益或失败是有效结果，不要求人为制造正效果。
- [ ] 汇总五阶段验证，运行相关后端回归、Ruff、RAG Recall@3门禁及健康检查；更新结论账本和计划勾选。新的mock、真实模型、外部人工缺口分别报告，绝不将准备材料记作已完成审查。

## 当前检查点

- 2026-10-17：只读交接已保存到 `W:\大论文\论文规划\实验项目交接报告.md`；claims结构通过但RQ5阻塞；E1规格通过，7200条历史记录重计数无缺失。尚未运行五阶段的新实验。
