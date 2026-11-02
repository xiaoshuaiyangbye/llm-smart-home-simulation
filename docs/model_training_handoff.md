# 模型训练工程交接

2026-10-26，用户授权将DeepSeek7B微调工程独立至 `P:/smart-home-model-training/`，随后授权审查并删除原工程不再需要的文件。

## 当前职责

| 工程 | 内容 |
| --- | --- |
| `P:/llm-smart-home-simulation/` | 前后端、数字孪生仿真、运行时智能体、RAG、既有实验与论文证据 |
| `P:/smart-home-model-training/` | 训练代码、独立Python环境、训练数据、基础权重、checkpoint、adapter与离线推理评测 |

新工程根目录README.md说明使用方法。训练状态入口是 `runs/current.json` 和 `status.ps1`。2026-10-26 本地 250-step 续训和 200 条合成留出样本的 base/adapter 配对评测已完成；adapter schema-valid rate 为 100%，exact ordered-call rate 为 91%，base 对应为 0%/0%。这是与共享模板的合成软件标签配对结果，不能称为独立语义泛化、解释质量、安全性或真实设备改进。指标与哈希见 `P:/smart-home-model-training/runs/resumed-20261026-v1/evaluation/summary.json`。

独立 loopback planner 服务在 `src/local_finetune/serve.py`；HTTP 健康状态为 `http://127.0.0.1:8011/health`，`POST /plan` 仅返回 schema-validated 候选计划。EnergyPlus integration 仍需要经过项目 Harness 的安全、critic 与单区 actuator 能力检查，未连接到原系统总控 LLM 路由。

## 原路径与保留位置

| 已清理的原路径 | 独立工程内的保留位置 |
| --- | --- |
| `output/local-finetune/base-model/` 完整权重 | `models/DeepSeek-R1-Distill-Qwen-7B/`，文件SHA-256一致 |
| `output/local-finetune/dataset-v*/` | `data/dataset-v*/` |
| `output/local-finetune/run-20261026-v1/` | `runs/source-run-20261026-v1/`；状态差异另存归档 |
| `output/local-finetune/` 其他来源记录 | `docs/`及`archive/original-project-training-20261026/` |
| `tools/local_finetune/` | 当前代码在`src/local_finetune/`；原版在归档`source-files/tools/local_finetune/` |
| 原训练方案与发现清单 | 归档`source-files/docs/`与`source-files/output/` |

逐文件来源、保留位置与SHA-256见独立工程 `archive/original-project-training-20261026/preservation-manifest.json`，共118个文件有保留/一致性记录。原账本中的历史命令和路径保留其当时含义，查找产物请按此表映射；当前claim matrix已改为新的实际证据路径。

本轮移出对象只包括已迁移且核验的重复训练文件、旧训练环境、未完成模型下载缓存和可重建的项目缓存/安装包。批量永久删除被自动安全检查拒绝（`blocked by policy`，未返回详细原因），实际采用可恢复移动：23项目录/文件位于 `P:/project-cleanup-quarantine-20261026/`，恢复映射见其中的 `restore-manifest.json`。原项目减少约42.0GB，但物理磁盘释放为0；不可将隔离表述为已经永久删除。

保留仿真源码及其未提交修改、`data/results/`、`data/logs/`、`data/private_memory/`、前端依赖、后端环境和已安装运行时。清理明细与实际验证见`output/project-cleanup-audit-20261026/`和`docs/improvement_backlog.md`。

这次交接与清理不新增模型泛化、安全、真实设备或人工语义评审证据。
