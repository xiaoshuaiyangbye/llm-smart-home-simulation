# 现场与标注验收协议

本项目是仿真平台。以下清单定义了将软件证据升级为真实模型或现场结论前必须保存的可审计输入。

> Retrieval summary: field validation for real devices requires an isolated environment, firmware inventory, tested rollback, manual emergency stop, fault injection, calibrated sensors, raw logs, and an artifact manifest. It is not simulation evidence.

## 语义标注裁决

每个存在多种合理动作粒度的任务必须记录：任务 ID、原始指令、候选语义、裁决动作、裁决人、日期和理由。未裁决项目不得作为模型错误或基准准确率分母。

例如，“打开一些”可表示 `turn_on` 或带开度参数的 `set_target`；研究者必须在版本化标签中明确选用哪一种。

## 真实设备验收

在宣称真实设备控制、安全或节能之前，必须保留以下数据：

1. 设备型号、固件、网关版本和受控实体清单。
2. 隔离测试环境、回滚动作、人工急停机制和故障注入记录。
3. 原始传感器读数、校准信息、时间同步方法和缺失数据处理。
4. 对照策略、预注册指标、采样窗口、负载/并发配置及原始日志清单。
5. 实验产物的 SHA-256 清单；使用 `scripts/verify_artifact_integrity.py` 创建并验证。

缺少任一项时，结果只能表述为仿真或软件集成证据。

## 可执行验收入口

填写 `data/field_validation/field_validation_evidence.example.json` 的副本，
并在原始现场产物目录运行：

```powershell
.\backend\.venv\Scripts\python.exe scripts\verify_artifact_integrity.py create <artifact-directory>
.\backend\.venv\Scripts\python.exe scripts\validate_field_validation_evidence.py <completed-evidence.json>
```

只有验证器返回 `accepted: true`，且证据来自实际隔离环境，才具备提出对应真实设备结论的最低可审计输入。验证器不产生现场数据，也不把仿真结果提升为真实设备证据。
