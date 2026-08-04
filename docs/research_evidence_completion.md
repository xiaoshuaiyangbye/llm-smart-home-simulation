# 研究证据完成清单

本仓库可以验证软件、仿真与证据文件的完整性；它不能替代独立人工判断或实体设备实验。以下清单用于把当前可复现软件证据升级为可答辩的研究材料。

**2026-07-16 状态：** RQ1 guarded/unguarded 对照、RQ3 三个故障机制任务簇和 RQ5 固定 qwen3:8b digest 的 36 任务×3 重复真实模型实验已经完成。当前软件论文投稿门禁只剩两名真实独立标注者与第三方分歧裁决。双盲任务包位于 `data/research/semantic_review_packets/20260716_032525/`；包内不含版本参考答案，`manifest.json` 明确保持 `review_status=not_started_external`。

## 1. 独立语义标注审查

1. 复制 `data/tasks/semantic_annotation_review.example.json`，为全部任务填写两名独立审查者的标签。
2. 对每一处不同意见记录非审查者的裁决者、理由和最终标签；P003 必须包含这一记录。
3. 将 `task_suite_sha256` 替换为当前任务集的 SHA-256，并执行：

```powershell
.\backend\.venv\Scripts\python.exe scripts\validate_semantic_annotation_review.py <完成的审查文件.json> --tasks data\tasks\reproduction_tasks.json
```

校验器通过只证明审查记录完整、一致且绑定到当前任务集；它不会证明审查者身份或独立性。因此，审查原件、角色关系和日期仍须随论文材料保存。通过后才能将任务集中的三项标注证据状态改为 `recorded`。

## 2. 真实模型基准

运行前固定模型摘要、服务端版本、解码参数、任务集 SHA-256 和环境配置。至少覆盖所有任务类别，并另行设计并发、失败率和延迟试验；默认复现实验的百分比只描述固定仿真任务集，不能外推为总体模型性能。

任何失败运行都必须保留在原始记录中，不能从稳定性或准确率分母中删除。高保证产物目录必须从仓库外注入 `ARTIFACT_SIGNING_KEY`，使用 `scripts/verify_artifact_integrity.py create <目录> --require-signature` 创建 HMAC-SHA256 清单，并在提交前使用同一密钥复验。签名只能证明持有共享密钥的一方生成了当前清单，不能替代访问控制、密钥轮换或不可变对象存储。

## 3. 真实设备与现场

填写 `data/field_validation/field_validation_evidence.example.json`，采集真实设备清单、隔离与急停、回滚、校准、原始传感器数据、对照策略、预注册指标和原始日志。原始产物必须先创建带签名清单，再在同一 `ARTIFACT_SIGNING_KEY` 环境中执行 `scripts/validate_field_validation_evidence.py`；无签名、缺密钥、签名不匹配或文件变化都会 fail closed。

在该证据文件通过且原始数据可核验前，所有结论只能表述为软件仿真或探索性实体测试，不能表述为真实全屋安全性或节能效果。
