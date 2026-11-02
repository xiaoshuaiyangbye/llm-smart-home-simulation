# 2026-10-26 项目审查与瘦身

## 实际结果

原项目中的DeepSeek训练目录和训练代码已移出，运行中的训练使用独立工程 `P:/smart-home-model-training/`。

| 项目 | 实测结果 |
| --- | --- |
| 原项目清理前逻辑文件体积 | 43,394,776,214 bytes，约43.39GB |
| 清理后体积（验证过程中） | 1,382,212,511 bytes，约1.38GB |
| 移出内容 | 23项，42,014,522,053 bytes，约42.01GB |
| 实际物理磁盘释放 | 0 bytes；本轮是可恢复隔离，尚未永久删除 |
| 隔离目录 | `P:/project-cleanup-quarantine-20261026/` |

批量递归永久删除被自动安全检查拒绝，返回`blocked by policy`，没有提供更详细原因。因此改为移动到隔离目录；未绕过永久删除限制，也不将移出项目表述为已释放磁盘。

## 已审查与处理

- `output/local-finetune/`约41.88GB：重复基础权重、旧Python训练环境、未完成下载、已迁移数据及历史试训。删除前的替代步骤是先核验独立工程副本并补存唯一来源记录，再移出整个旧目录。
- `tools/local_finetune/`、原训练方案、发现清单：归档原始版本，当前入口统一为独立工程。
- `.runtime/downloads/`与`.runtime/npm-cache/`：可重建的安装下载和包缓存，共约131MB，已隔离；已安装Python/Node和项目依赖保留。
- 项目Python编译缓存、pytest/Ruff缓存：已隔离。验证会重新生成少量缓存，这是正常行为；新增Git忽略规则。
- Docker构建上下文增加排除`output/`、Ruff缓存、浏览器证据和前端测试报告；已检查后端/前端Dockerfile的COPY输入不依赖这些目录。
- 当前论文claim matrix的训练证据路径改为独立工程；历史账本保留当时路径，并提供[迁移映射](model_training_handoff.md)。

118个训练相关文件已核验独立工程副本或复制并校验SHA-256。完整来源清单在独立工程`archive/original-project-training-20261026/preservation-manifest.json`。隔离目录中的`restore-manifest.json`记录原路径和隔离位置。

## 保留内容与边界

保留原有未提交业务代码、仿真/研究模块、测试、`data/results/`、`data/logs/`、`data/private_memory/`、后端环境、前端依赖及已安装运行时。约725MB既有实验结果是研究证据，不因体积较大而删除。没有仅凭文件名或暂时无引用就删除研究脚本，也没有删除前端3D依赖；3D仍是现有功能并采用延迟加载。

本轮审查覆盖目录占用、运行路径依赖、迁移来源、构建上下文和质量门禁，不是逐行安全审计，也不构成独立论文语义评审。

## 验证

- 后端：`backend/.venv/Scripts/python.exe -m pytest backend/tests -q`，257 passed。
- 静态检查：backend/app、backend/tests、scripts的Ruff全部通过。
- 前端：12 tests passed；TypeScript/Vite生产构建通过。
- bundle gate：2D初始JavaScript 216,091 bytes；延迟3D gzip 273,756 bytes，均在预算内。构建中的大chunk提示对应延迟3D，未据此进行额外重构。
- 本地`/health`、`/api/agent/health`均无法连接；Docker engine不可用。未启动或重部署原系统，未获取新的浏览器运行证据。
- 独立模型训练在隔离后仍持续推进；这证明运行路径未依赖旧目录，不证明训练已完成或模型效果改善。

详细机器记录位于`output/project-cleanup-audit-20261026/`。最终RAG与claim结构检查结果登记在改善账本；RQ5仍需独立人工审查。
