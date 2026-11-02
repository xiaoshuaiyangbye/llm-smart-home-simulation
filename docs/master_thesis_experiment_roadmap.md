# 硕士论文实验深度持续推进表

更新时间：2026-10-26

本文档是持续化任务的工作台，维护两个表格：

1. 现有问题与深入方案；
2. 推荐的硕士论文实验包。

每轮自动任务只能推进一个最高优先级、可验证的问题。若下一步会改变实验 fixtures、controls、metrics、hypotheses 或解释政策，且既有用户指令没有授权或明确涵盖该选择，必须先标记为“需要用户研究设计确认”。用户“请把1-4按顺序完善”已授权本轮四阶段软件实现；该授权不等于 D1 论文章节重排、独立人工标签评审或真实设备实验完成。

## 现有问题与深入方案

| 编号 | 状态 | 优先级 | 现有问题 | 哪里需要深入 | 前沿方法参照 | 解决办法 | 验收标准与证据路径 | 边界 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D0 | 已建立追踪表与状态审计 | P0 | 两个表格原本只存在于对话中，后续持续任务缺少稳定的仓库落点，容易变成散乱记录。 | 建立可版本化、可被 `rg` 检索、可被 backlog 追踪，并可被脚本审计的论文实验路线图。 | Evidence ledger、reproducible research checklist。 | 新增本文档，并在 `docs/improvement_backlog.md` 追加本轮记录；新增 `scripts/summarize_master_thesis_experiment_roadmap.py` 将两张表解析为 machine-readable status。 | 本文件存在；`rg "硕士论文实验深度持续推进表" docs` 可定位；`scripts/summarize_master_thesis_experiment_roadmap.py` 能输出 17 行状态、用户确认项、外部人员项和 full benchmark/real bridge 待办项；RAG 门禁通过。 | 这是研究治理修复，不新增实验结果。 |
| D1 | 待用户确认 | P0 | 研究问题过多，RQ1-RQ6 容易分散；硕士论文主线不够聚焦。 | 将论文主线压缩为 3 个核心贡献：异步状态安全提交、故障/扰动安全鲁棒性、显式反馈门控个性化。 | Design science, systems paper evaluation matrix。 | 将 RQ4 作为证据基础设施，RQ5 作为横向模型验证，避免每章都写成主创新。 | 更新 `docs/thesis_argument_chain.md` 的章节映射；`scripts/validate_thesis_claims.py --require-generated-evidence` 仍通过。 | 章节重排属于论文研究设计，需要用户确认后执行。 |
| D2 | full matrix 已完成 | P0 | RQ1 已有 guarded/unguarded 100 次交错，但场景矩阵仍窄。 | 已加入 delay、event rate、fault rate、planner policy 的系统压力矩阵。 | ReliabilityBench 的 pass^k、语义扰动与工具/API 故障注入；tau-bench 的 repeated reliability。 | 已扩展 `scripts/run_snapshot_commit_experiment.py`，支持 `--matrix smoke|full`，比较 unguarded、global_lock、optimistic、optimistic_replan；实现规格见下方“D2/E2 RQ1 压力矩阵规格”。 | smoke 24 traces 与 full 4800 traces 均已生成；full 产物：`data/results/snapshot_commit/20260901_023151/summary.json`、`records.csv`、`report.md`。 | 仍是软件仿真，不证明硬实时或真实设备安全。 |
| D3 | safety taxonomy full matrix 已完成 | P0 | RQ3 原本只有 3 类构造安全故障，安全深度不足。 | 已建立 15 类 smart-home safety fault taxonomy，并扩展到多方法、多任务变体和 repeat seeds；角色消融 full 仍由 D4/E3 追踪。 | SmartBench 的 15 anomaly categories；AgentDojo 的工具攻击/间接注入安全评测；VerifAI falsification。 | 扩展 `scripts/run_safety_fault_taxonomy_experiment.py`，支持 `--matrix smoke|full`；full 比较 `no_review`、`safety_review`、`critic_review`、`full` 四组，覆盖 15 类 x 20 variants x 3 repeat seeds。 | full 3600 records 已完成；产物：`data/results/safety_faults/20260901_120915/summary.json`、`records.csv`、`report.md`。 | 构造 taxonomy 不等于真实家庭故障分布；当前 full matrix 仍是组件级软件 fault fixture，不是完整端到端 episode benchmark 或真实设备安全实验。 |
| D4 | role-ablation full matrix 已完成 | P0 | 多智能体贡献此前主要靠故障场景，普通任务中 static 与 single 无差异。 | 已将组件级 frozen-plan 角色消融扩展到 200 unique task variants、6 groups、3 repeat seeds，并记录 safety、critic、feedback、execution 对 final-state success、recovery success、side-effect 和 latency proxy 的贡献边界。 | SimuHome 的多 agent/tool-use episode benchmark；tau-bench 的 final state verification。 | 扩展 `scripts/run_role_ablation_experiment.py`，支持 `--matrix smoke|full`，覆盖 single、planner-only、+safety、+critic、+feedback、full 六组；full 由普通照明、高危安全故障和中等能耗冲突模板生成 200 个确定性任务变体。 | full 6 groups x 200 tasks x 3 repeats = 3600 records 已完成；产物：`data/results/role_ablation/20260901_131011/summary.json`、`records.csv`、`report.md`。 | 当前仍是组件级 frozen-plan 软件消融，不是完整 TaskRunner 端到端 episode benchmark；+feedback 在该构造 full matrix 中仍未观察到 correction，不能写全面优越。 |
| D5 | longitudinal personalization full matrix 已完成 | P1 | RQ2 此前主要是固定画像效果，不能支撑“反馈学习带来个性化提升”。 | 已将纵向 personalization 扩展到 30 profiles、30 turns、4 methods、3 repeat seeds，并分开记录 feedback gate、confirmed_experience visibility、unauthorized prior exposure、pre/post utility、comfort proxy、energy proxy 与 safety override。 | IoTGPT 的 Decompose-Derive-Refine 与 subtask memory reuse；longitudinal adaptive personalization。 | 扩展 `scripts/run_personalization_longitudinal_experiment.py`，支持 `--matrix smoke|full`，比较 no memory、static profile、ungated memory、gated confirmed memory。 | full 30 profiles x 30 turns x 4 methods x 3 seeds = 10800 records 已完成；产物：`data/results/personalization_longitudinal/20260903_074306/summary.json`、`records.csv`、`report.md`。 | 当前是组件级软件 full matrix 和确定性 preference-alignment proxy，不是真实住户反馈，也不是完整 TaskRunner episode 效用。 |
| D6 | RAG knowledge full matrix 已完成 | P1 | RAG 此前主要是检索可用性，未充分评估 stale/conflicting/malicious knowledge 对控制的影响。 | 已将合成 RAG 知识条件扩展到 100 base task variants、5 conditions、3 repeat seeds，并把 planner_only 风险、安全审查后剩余风险、source provenance、hierarchy violation 与 attack recall/false-positive proxy 分开记录。 | AgentDojo indirect prompt injection；RAG robustness and provenance evaluation。 | 扩展 `scripts/run_rag_knowledge_robustness_experiment.py`，支持 `--matrix smoke|full`；full 比较 no RAG、correct RAG、stale RAG、conflicting RAG、malicious RAG 五组，并含 planner_only 与 safety_review。 | full 1500 knowledge trials / 3000 review records 已完成；产物：`data/results/rag_knowledge_robustness/20260903_064416/summary.json`、`records.csv`、`report.md`。 | 当前不改生产 RAG index，不测真实检索污染召回，也不等于真实 prompt injection 覆盖率或真实模型服从性。 |
| D7 | 全屋九热区 EnergyPlus 已接入并验证；实测校准待做 | P1 | 旧 EnergyPlus 只覆盖示例客厅，未覆盖用户设计空间。 | 统一户型多边形、九热区相邻传热/固定换气、房间设备映射、SQL 分房间与全屋对账。 | EnergyPlus Runtime/Data Transfer API。 | 新作业默认 whole_home；原 single_room 仅历史复现。 | 2026-10-27 summer/winter v2 各 rule/mock 两作业；每作业288时间点、2592房间样本、0 severe、分区/全屋电量残差0 J；Edge九空间结果与切换已验证。 | 3m层高、材料、气流、固定单房间占用与设备响应未校准；窗帘未映射，餐厅/走廊无外窗；不支持现场节能结论。 |
| D8 | 待外部人员 | P0 | RQ5 仍缺两名独立人工标注者和分歧裁决。 | 闭合语义标签有效性，不由代理冒充人工。 | Human annotation protocol, inter-rater agreement, adjudication。 | 使用 `data/research/semantic_review_packets/20260716_032525/`，收集两名独立标注和第三方裁决。 | `scripts/validate_semantic_annotation_review.py` 通过；重生成 RQ5 指标与图表。 | 必须是真实外部人员，不能自动完成。 |

## 推荐的硕士论文实验包

| 实验包 | 状态 | 对应问题 | 样本量与实验量 | 对照组 | 主要指标 | 统计方法 | 运行与产物 | 论文可写结论 | 不可越界结论 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E0 路线图与证据账本 | 已完成并可机器审计 | 后续持续任务缺少表格源文件与完成度判定 | 1 个 roadmap 文档 + 1 条 backlog 记录 + 1 个 status summarizer | 无 | 可定位性、表格完整性、RAG recall、blocker classification | 不适用 | `docs/master_thesis_experiment_roadmap.md`；`docs/improvement_backlog.md`；`scripts/summarize_master_thesis_experiment_roadmap.py` | 论文实验推进有稳定追踪表，且能区分已完成、需用户确认、需外部人员和待 full benchmark/real bridge 的条目。 | 不能说实验深度已全部完成；status summarizer 只审计路线图文本，不替代实验运行。 |
| E1 任务基准与方法横向验证 | 已获用户授权，限定软件矩阵已完成 | 完整 TaskRunner 的匹配方法比较和独立最终状态验证 | 24 个开发者基础场景，扩展为 600 配置 x 4 方法 x 3 seeds = 7200 mock runs；修复后 smoke 为 24 配置 x 4 方法 = 96 runs | single_agent、multi_agent_static、personalized、full；同一初始状态 hash 与后置 30 min 仿真步 | 开发者状态契约通过率 final_state_success、runtime success、适用时 device F1、开发者 intent 标签 semantic accuracy、实测 TaskRunner latency、energy、comfort、action-change trace | 按 base_task_id 聚类的描述性 paired bootstrap；原 mixed-effects/Holm 未执行 | `scripts/run_e1_episode_benchmark.py --matrix full`；已完成的修复前 full：`data/results/e1_task_benchmark/20260907_055214_523861/`；修复后 smoke：`data/results/e1_task_benchmark/20260907_092614_310836/`；规格与历史产物声明由 `scripts/validate_e1_episode_benchmark_spec.py` 校验 | 可报告各自产物冻结源码/协议下的固定软件场景权衡；最终 full 7200 已完成：`data/results/e1_task_benchmark/20260908_033452_721117/`；状态契约仅覆盖已声明谓词，E1-022–024 目前仅覆盖温度，不能解释为完整意图或安全达成。 | 600 配置和重复 seed 不是 600 独立总体任务；30 min kWh 是单步终点功率估计，动作批次另有未纳入时钟/能耗的 5 min 温湿度 relaxation，非等总物理时长或全控制成本；mock、开发者标签、脚本化反馈及隔离 lexical RAG 不证明真实模型泛化、真实用户学习或真实家庭效果；统计研究目标仍单列为未执行。 |
| E2 并发与过期提交压力矩阵 | 已完成 full matrix | RQ1 场景矩阵窄 | smoke 24 traces；full 4800 traces | unguarded、global_lock、optimistic、optimistic_replan | stale commit、valid commit、event-to-effect latency、overhead、replan count | paired comparison；cluster bootstrap CI；pass^k reliability | `scripts/run_snapshot_commit_experiment.py --matrix full`；`data/results/snapshot_commit/20260901_023151/` | 在虚拟 delay、事件概率和工具故障矩阵中，freshness gate 阻止过期提交，replan 策略可在拒绝后恢复执行。 | 不证明硬实时或真实设备安全。 |
| E3 故障与安全鲁棒性 | taxonomy full 与 role-ablation full 均已完成 | RQ3 故障 taxonomy 不足、角色贡献不清 | safety taxonomy full 3600 records + role-ablation full 3600 records | taxonomy full: no_review、safety_review、critic_review、full；role full: single、planner-only、+safety、+critic、+feedback、full | detected、blocked、false block、recovery success、severity score、role action-change、final-state success、ordinary side-effect、latency proxy | per-category effect + macro average；cluster bootstrap；matched component contrast | `scripts/run_safety_fault_taxonomy_experiment.py --matrix full`；`data/results/safety_faults/20260901_120915/`；`scripts/run_role_ablation_experiment.py --matrix full`；`data/results/role_ablation/20260901_131011/` | taxonomy full 中 full 方法 high fault recovery_success_rate=1.0、false_block_rate=0；role full 中 full group final_state_success_rate=1.0、ordinary_task_side_effect_rate=0，+safety 修复 high fault，+critic 修复 medium energy conflict。 | 两个 full matrix 都是组件级确定性软件夹具，不代表真实故障分布、真实住户效果或完整端到端 TaskRunner 总体优越性。 |
| E4 显式反馈门控个性化纵向实验 | full matrix 已完成 | RQ2/RQ6 效用链未闭合 | smoke 40 records；full 30 profiles x 30 turns x 4 methods x 3 seeds = 10800 records | no memory、static、ungated、gated | utility、comfort proxy、energy proxy、confirmed experience visibility、override count、unauthorized prior exposure | longitudinal mixed model；profile random effects；pre/post component contrast | `scripts/run_personalization_longitudinal_experiment.py --matrix full`；`data/results/personalization_longitudinal/20260903_074306/` | full matrix 中 gated_confirmed_memory post-confirmation visibility=1.0、utility_gain_post_minus_pre=+8.616、unauthorized prior exposure=0；ungated_memory utility gain=+5.664，但 unauthorized prior exposure=2610。 | 模拟反馈不等于真实用户满意；proxy utility 不等于完整端到端 TaskRunner 控制效用或真实家庭节能。 |
| E5 建筑能耗外部有效性切片 | 全屋九热区桥接完成；单房间历史真实模型结果保留 | 示例客厅不能代表设计全屋 | 九热区同引擎，每房间独立环境与控制；夏冬各一次 rule/mock 单日配对 | rule、manual、Harness mock；真实 DeepSeek 全屋待验证 | 分房间温湿度/CO₂/照度、SQL模拟电量/热量与动作追踪 | 模型/天气/初态匹配，分房间与全屋电量逐区间核对；无独立重复推断 | `data/results/energyplus/comparisons/whole-home-summer-20261027-v2/comparison.json`、`whole-home-winter-20261027-v2/comparison.json` | 四作业均9区、288时间点、2592房间样本、0 severe、房间/全屋残差0 J；真实模型调用0；不作节能或方法优势判断。 | 未校准围护结构/3m层高/封闭阳台/固定跨区换气与占用；Ideal Loads非实测设备；窗帘未映射、餐厅走廊无实际外窗；未完成真实模型全屋、独立语义审查或现场测量。 |
| E6 用户研究或人工评审 | 需外部授权 | 真实用户/人工标签证据缺口 | RQ5 至少 2 annotators + adjudicator；可选 24-36 participants crossover | 原参考标签、两名独立标注、裁决标签 | agreement、semantic score after adjudication、SUS/UEQ 可选 | Cohen/Fleiss kappa；paired nonparametric tests | `data/research/semantic_review_packets/`；评审表单 | 标签有效性或交互体验的外部证据。 | 代理不能代替独立人工。 |
| E7 RAG 知识鲁棒性与间接注入实验 | full matrix 已完成 | RAG 错误知识可能污染控制决策 | smoke 30 records；full 100 base tasks x 5 RAG conditions x 3 repeats = 1500 knowledge trials，并展开为 3000 review records | no RAG、correct RAG、stale RAG、conflicting RAG、malicious RAG；planner_only、safety_review | unsafe action rate、instruction hierarchy violation、provenance coverage、blocked high fault rate、medium warning retention、attack recall/false-positive proxy | condition-level macro average；cluster bootstrap；attack recall/precision proxy | `scripts/run_rag_knowledge_robustness_experiment.py --matrix full`；`data/results/rag_knowledge_robustness/20260903_064416/` | full matrix 中 stale/conflicting/malicious 条件使 planner_only unsafe_action_rate_after_review=1.0；safety_review 将该值降到 0.33，malicious hierarchy violation rate=1.0，correct/no_rag false-positive proxy=0。 | 当前是合成知识条件矩阵，不代表真实攻击库覆盖、真实检索污染召回、真实 prompt injection 覆盖率或真实模型服从性。 |

## D2/E2 RQ1 压力矩阵规格

目标：把当前 `snapshot_commit_ablation_v1` 从单一 `state_revision_change` 场景扩展为可复现压力矩阵，同时保持生产默认的 guarded 行为不变。

| 维度 | smoke 值 | full 值 | 记录字段 | 说明 |
| --- | --- | --- | --- | --- |
| policy | `unguarded`, `optimistic` | `unguarded`, `global_lock`, `optimistic`, `optimistic_replan` | `policy` | `optimistic` 对应当前 guarded 新鲜度门禁；`global_lock` 是模拟锁内规划的基线；`optimistic_replan` 记录拒绝后是否生成新快照再提交。 |
| planner_delay_ms | 0, 250 | 0, 100, 500, 1000, 3000 | `planner_delay_ms` | 用确定性虚拟 delay 记录慢速 LLM 规划窗口，不做真实 sleep，以免实验耗时膨胀。 |
| event_rate | 0.0, 1.0 | 0.0, 0.25, 0.5, 1.0 | `event_rate` | 表示快照后到提交前发生状态变化的概率；smoke 固定两端点。 |
| fault_rate | 0.0 | 0.0, 0.05, 0.2 | `fault_rate` | 表示提交阶段设备确认失败或工具/API 故障概率；先在隔离 runner 中模拟，不改生产执行路径。 |
| traces | 3 | 20 | `trace_id`, `seed` | 以 task-cluster/seed 为不确定性单位；重复不是独立总体样本。 |

最小实现要求：

| 项 | 要求 |
| --- | --- |
| CLI | 增加 `--matrix smoke|full`，默认保持现有窄实验行为，避免破坏旧报告。 |
| schema | 新报告使用 `snapshot_commit_pressure_matrix_v1`；旧 `snapshot_commit_ablation_v1` 保留。 |
| 指标 | 至少输出 `stale_committed_rate`、`valid_commit_rate`、`median_commit_decision_latency_us`、`p95_commit_decision_latency_us`、`replan_success_rate`、`simulated_fault_rate`。 |
| 回归 | `backend/tests/test_snapshot_commit_experiment.py` 覆盖 smoke matrix 记录数、policy 覆盖、旧默认行为不变。 |
| 边界 | 报告必须写明 planner delay 是虚拟软件变量，不是实际 LLM 响应时间或真实 presence 事件时延。 |

## 下一轮默认优先级

若用户未改变方向，下一轮先运行 `scripts/summarize_master_thesis_experiment_roadmap.py` 审计状态。E1 已有实际 TaskRunner full 7200 mock 与修复后 smoke 96 产物；四阶段最终 full 已完成并保存于 `data/results/e1_task_benchmark/20260908_033452_721117/`，对应状态契约 v2；详见 `docs/four_stage_completion_20260909.md`。D7/E5 已增加 EnergyPlus 物理软件桥接；后续优先完成 DeepSeek 配对评测接入、用户房间/照明测量校准及多季节匹配运行。D1 章节重排仍需用户确认，D8/E6 仍需要真实外部人员。

E1 的 `software_verified_complete` 仅指授权范围内、已运行的限定软件配置矩阵。`bounded_software_complete_ids` 单列该范围；状态脚本仍是文档审计，不替代原始记录校验。原 mixed-effects model 与 Holm correction 保留为未执行研究目标，当前 base-scenario cluster bootstrap 仅描述固定开发者场景中的差异，不报告总体显著性。既有 full 与修复后 smoke 及最终 full 可能对应不同源码、状态谓词 fixtures 和配置规模；应按各自产物冻结指纹报告，不能把跨版本差值直接解释为控制修复的因果效果。


## 补充验证 2026-10-17 显式设备约束修复与新验证

Problem: 接手中断工作，已证实制热指令误生成cool；复合否定被整句屏蔽，区间目标缺少保持。原红灯日志保留在 output/five-stage-20261017-preexisting/explicit-red.txt。
Minimum fix: 沿用本轮已有explicit_device_control_v2修改：按子句处理否定，保留模式与区间，拒绝禁止模式/越界/倒置区间，空调通过turn_on同时提交模式与温度。单设备族确定性适配器不代表通用自然语言理解。
Verification evidence: 本次重新运行 test_explicit_control.py、test_semantic_targets.py、test_e1_episode_benchmark.py：57 passed；explicit_control.py与test_explicit_control.py Ruff通过。新E1 smoke为96条，四组runtime均100%，开发者状态契约通过率single/static/personalized/full=79.17%/87.5%/100%/100%；产物 data/results/e1_task_benchmark/20261017_153220_182395/。localhost:80的/health和/api/agent/health均连接拒绝，当前无新服务/API/页面验证。
Research implication: 限定软件路径的显式设备约束保持已有针对性回归和TaskRunner smoke证据。
Research boundary: 新产物全部mock，不是完整7200矩阵复跑；不同版本和规模不能作因果改善对比。单设备族与已覆盖子句形式不证明任意复合语句支持；区间中点是确定性执行策略，不是学习/优化结果。
Residual risk: 独立语义评审、真实模型复测、未覆盖语言形式、统一仿真时钟与全控制能耗、真实设备验证仍未完成；RQ5保持阻塞。


## 2026-10-17 第二轮：无标点指令与独立积分核算

Problem: 新增无标点复合否定3例修复前全部失败，亮度40%被吞掉或冲突错误成功。另以现有模拟器复现：一个控制批次温度26.00变25.39但时钟/能耗不变；一次30分钟与30次1分钟产生不同状态与能耗。
Minimum fix: explicit_control仅在把/将+亮度/温度/速度/开度的明确边界补充分句。新增IntegratedSmartHomeEnvironment为opt-in动作/步进核算模式，原环境保持历史行为；默认成功批次5分钟，分钟终点功率积分，零时长不推进，部分成功批次计一次时长。新增诊断runner冻结初态、配置及源码哈希。
Verification evidence: 无标点测试先3 failed后通过；定向60 passed，积分环境7 passed；最终全后端251 passed，相关Ruff通过。当前代码（添加积分模块之前）的E1 full已运行7200 mock records，目录data/results/e1_task_benchmark/20261017_153640_135596/；原始配对1800组与summary重算无异常，四组runtime均1，状态契约通过率single/static/personalized/full=77.5%/90%/100%/100%。独立积分诊断data/results/integrated_accounting/20261017_154016_540080/有6条记录，固定总30分钟、重复批次终态一致、正能耗三项检查均通过。
Research implication: 明确参数子句不再因缺标点被整段忽略；动作与观察的时间/能耗核算有可单独启用的版本，能做一致性诊断。
Research boundary: 新E1 full仍使用legacy核算，不是integrated模式；新增积分模式只验证设备动作与step路径，不能宣称所有环境变更API已统一。6条是确定性核算诊断，无LLM调用、无方法优越性或节能结论；每分钟终点功率矩形积分和累计kWh的5位舍入仍是数值近似。仿真模型未现场标定，历史/新full不可直接作修复因果比较。
Residual risk: 无标点解析只覆盖声明边界，其余混合否定/多房间多设备族尚未充分验证；积分模式尚未接入新版E1。RQ5人工审查、真实模型复测与照明原始数据核验未完成。127.0.0.1:11434/api/tags及8000/health拒连；localhost/health超时，无本次在线服务或浏览器证据。

只读审计补充：积分诊断13个源码/配置哈希与当前文件一致；未发现阻止本轮交付的具体缺陷。分步等价和固定总时域仅在refresh_realtime=False下验证，默认实时刷新路径未验证；不能泛称所有环境API的时钟/能耗已统一。


## 2026-10-18 新积分协议E1完整矩阵与论文初稿

Problem: opt-in积分环境原先只完成6条核算诊断，尚未进入完整TaskRunner方法比较。
Minimum fix: run_episode新增默认legacy不变的accounting_mode路径；integrated_total_30m_v1在相同冻结初态上计入控制阶段，余时观察补足30分钟；旧utility/post_control_horizon_kwh置null；新增独立runner、配对校验与冻结源码包。
Verification evidence: 先5个新测试失败，接口接入后通过；最终257后端测试通过，相关Ruff通过。新smoke96条目录data/results/integrated_e1/20261017_154839_166050/；新full7200条目录data/results/integrated_e1/20261017_154901_058487/。独立审计逐条核验7200记录/trace、1800配对完整初态一致、所有总时间及control+post=30、whole_episode能耗等于after-before最大误差0、summary均值一致、80源文件及冻结spec/tasks哈希匹配。225条含独立legacy环境中的脚本训练，评价初态未污染。
Research implication: 新协议能够在固定总30分钟软件时域中比较动作与观察；四组状态契约通过率77.5%/90%/100%/100%。全记录平均能耗为0.188086/0.186976/0.187512/0.187512 kWh，舒适代理95.124/95.097/94.969/94.969。按24基础场景等权事后描述性分析，full相对single契约差22.92pp；能耗差区间跨零，不作显著性或全面节能结论。
Research boundary: mock、开发者标签和状态谓词、未现场标定；准备及独立训练在评价时域外；分钟终点功率+5位累计舍入为近似。无真实模型或物理实验新证据。dependency_source_sha256指基础manifest，新增runner有独立SHA和源码快照，不将其称为最终80文件整体哈希。
Residual risk: 独立人工语义评审、真实模型留出任务复测、照明原始数据核验未完成；六章工作初稿已建立但正文规模和格式检查仍进行中。


## 2026-10-18 时间离散敏感性证据同步

Problem: 已生成并写入论文的时间步诊断尚未同步进实验账本。
Minimum fix: 登记现有冻结产物，不修改任务、指标、控制方法或解释政策。
Verification evidence: data/results/time_discretization/20261017_160838_122257/summary.json：9场景、4步长、36记录，全部总时域30分钟；步长1/2/5/30分钟。相对一分钟参考，平均绝对能耗差0/0.000456667/0.001623333/0.009814444 kWh，平均绝对终温差0/0.031111/0.043333/0.206667℃。
Research implication: 时间离散是必须冻结的数值实验条件，与控制方法比较分开解释。
Research boundary: 合成软件诊断、无LLM调用；一分钟仅为数值参考，不是物理真值，不增加真实模型或现场证据。
Residual risk: 真实功率及热湿标定、独立语义审查仍未完成；RQ5保持开放。


## 2026-10-26 本地 DeepSeek QLoRA：准备完成、完整训练已启动

Problem: 用户希望仅用本机微调同时输出规划、简短解释和工具调用的小模型；当前接口仅使用Qwen语义解析，未具备可追溯训练链路。
Minimum fix: 新增独立 tools/local_finetune/，不改生产模型配置；固定DeepSeek-R1-Distill-Qwen-7B revision 916b56a44061fd5cd7d6a8fb632557ed4f724f60，建立Python3.12/CUDA12.6/NF4环境、规则合成数据、assistant-only loss训练与配对推理评测。只读审计发现dataset-v1温度标签与模拟器开机副作用冲突，已修正；v1至v4保留为被拒绝或被替代候选，当前使用dataset-v5。
Verification evidence: 40个针对性pytest通过，相关Ruff通过。GPU NF4实际前后向通过；两片官方权重均通过LFS SHA-256。dataset-v5为2000/200/200样本、每组24类，变化状态及条件分支均有覆盖；2400条审计、2729调用全部被模拟器接受，未请求设备不变；完整规范化指令与kind×room组合不跨split。真实tokenizer的20样例回答掩码与prompt还原通过（初始v3现场检查）；v5完整tokenize审计最大train/validation长度1111/1110，上限2048。7B真实GPU两步pilot训练7.5469秒，峰值allocated显存11826972160 bytes；adapter已保存，8条验证loss计算完成。完整训练与200条配对评测流程已启动，状态 output/local-finetune/run-20261026-v1/status.json；此处不记录为完成。RAG Recall@3=6/6；localhost/health=200，/api/agent/health本次5秒超时，未获取新的浏览器证据。
Research implication: 具备本机运行7B QLoRA的实际试训证据与可追溯训练/评测入口；不再仅有微调计划。
Research boundary: synthetic_rule_v1、human_reviewed=false；kind×room组合留出共享模板，同一split可有相同指令配不同状态。2步pilot只证明训练路径，loss不证明模型改善。尚无完整训练完成、配对推理收益、解释语义、端到端安全或真实设备结论；未替换现有Qwen配置，RQ5独立审查未闭合。
Residual risk: 完整任务仍运行；持续状态以status.json和training/progress.json为准，完成后需补录实际评测及失败项。全流程失败会保留phase日志和failed状态，不自动切换生产模型。


## 2026-10-26 模型训练工程独立打包与断点迁移

Problem: 用户要求模型训练从前后端仿真工程分离，在P盘建立独立工程。
Minimum fix: 创建P:/smart-home-model-training/，包含src/local_finetune、data、models、runs、独立.venv、PowerShell入口和最小compatibility/simulator接口快照。复制而非删除原文件，消除运行时对原项目路径的依赖。新增resume参数，核对数据SHA、模型revision和关键超参数后加载checkpoint中的adapter、optimizer、scheduler、RNG。
Verification evidence: 新工程41个pytest通过，Ruff通过；2400条数据、2729调用审计通过；9个复制后的模型文件SHA-256全部匹配。旧进程在63步停止，最近完整checkpoint-60和原run已复制并记录hash；新工程已实测恢复到61/250步。原第61-63步未落盘进度重算，原日志保留。新任务状态P:/smart-home-model-training/runs/resumed-20261026-v1/status.json，优化进度training/progress.json；原任务status标记migrated。
Research implication: 训练工程独立于前后端应用，固定数据、模型和关键超参数的续训有可追溯checkpoint来源。
Research boundary: 训练仍进行中；不新增模型收益、解释质量或真实设备安全结论。历史快照保留原绝对路径是来源记录，不代表新运行依赖原工程。兼容接口快照不包含Web服务或UI。
Residual risk: 完整训练和配对评测尚未完成，最终状态应读取新工程runs/current.json指向的任务；RQ5人工审查仍未闭合。


## 2026-10-26 项目审查与瘦身（冗余隔离，未永久删除）

Problem: 训练工程已独立，但原项目保留约41.88GB重复训练目录及约131MB可重建运行时下载/npm缓存，当前模型证据路径仍部分指向旧目录。
Minimum fix: 先核验/补存118个文件的独立工程副本与SHA-256，再把23项冗余移出至P:/project-cleanup-quarantine-20261026/。批量递归永久删除被自动安全检查拒绝（blocked by policy，未提供详细原因），实际执行可恢复移动，不冒称永久删除或释放物理磁盘。新增模型交接及审查报告、Git缓存忽略与Docker上下文排除；更新当前claim证据路径，保留历史账本映射。
Verification evidence: 原项目43,394,776,214 bytes降至验证时1,382,212,511 bytes；移出42,014,522,053 bytes，物理磁盘释放0。backend pytest 257 passed，Ruff通过；frontend 12 tests passed，生产构建与bundle gate通过（2D 216091 bytes；deferred 3D gzip 273756 bytes）。两健康接口无法连接，Docker engine不可用，未获取新浏览器证据。独立训练在隔离后继续运行。明细docs/cleanup_review_20261026.md、output/project-cleanup-audit-20261026/quarantine-results.json；隔离目录restore-manifest.json可定位恢复。
Research implication: 应用工程与训练资源分离，当前训练证据有可用的新路径；本轮无研究方法或仿真语义变更。
Research boundary: 保留data/results、data/logs、data/private_memory、业务源码及未提交修改、前后端依赖和已安装运行时。不把质量门禁或路径独立性解释为模型改善、在线部署正常或真实设备证据。
Residual risk: 永久删除未完成，冗余仍占隔离目录的物理磁盘；在线服务本次未验证，完整模型训练与配对评测仍运行，RQ5人工审查未闭合。

## 2026-11-01 独立V3工程联调进展（未整体验收）
训练及完整评测见P:/smart-home-model-training/runs/v3-durable-20261029/evaluation-report-20261030.md。已验证有限真实模型TaskRunner、35设备组件映射、HTTP门禁及单热区照明EnergyPlus；全屋真实模型与自然语言有效性仍未验证，D7/E5不升级为全屋完成或节能优势。新开关修复pilot独立于V3，开发门禁未验收；103条注册表请求已冻结但尚未推理。范围和残余项见训练工程docs/integration-acceptance-status-20261101.md。synthetic、human_reviewed=false，无独立人工或现场证据。
