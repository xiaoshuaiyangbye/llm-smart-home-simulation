# 2026-10-27 代码审查与项目瘦身

## 已修复的审查发现

| 问题 | 最小处理 | 验证 |
| --- | --- | --- |
| 路线图汇总依赖旧状态关键词，D7/E5 更新后未被正确分类 | 新增 physical_bridge_verified_calibration_pending 与 requires_physical_calibration_or_validation，明确已桥接、待校准；不归入 software_verified_complete | 全量后端269通过，含已桥接但未校准不得计入完成的回归 |
| 前端跨目录引用共享户型JSON，但Dockerfile未复制该输入 | COPY data/energyplus/home_layout.json 到构建阶段的 /app/data/energyplus/ | 新增构建输入契约测试；本机生产构建通过。Docker daemon不可用，未实际构建镜像 |
| 助手流程简化后仍保留无用RAG计数 | 删除无用计算，启用noUnusedLocals/noUnusedParameters | 严格TypeScript构建通过 |
| 已替换的旧WebGL 2D渲染路径与旧主题仍留在项目 | 备份并校验SHA-256后移除HomeScene2D.tsx、styles-v2.css；HouseScene只负责3D，HomePlan2D继续负责SVG 2D；删除无调用home-vitals旧CSS | 2D/3D浏览器回归通过，Edge 3D截图正常且0 page errors |
| 无引用的@react-three/drei及附带依赖 | npm uninstall，保留package-lock.json一致性；移除52个package条目 | build、Vitest和Playwright通过 |

## 瘦身实测

| 项目 | 前 | 后或去向 | 变化口径 |
| --- | --- | --- | --- |
| frontend/node_modules逻辑文件体积 | 281,454,329 bytes | 169,761,422 bytes | 减少111,692,907 bytes，约111.69MB |
| 已安装EnergyPlus的原始安装ZIP | 254,821,638 bytes留在项目 | 移到P:/project-cleanup-quarantine-20261027-code/installers/ | 项目移出约254.82MB；不等于物理磁盘释放 |
| 项目编译/pytest/Ruff缓存 | 16个缓存目录，2,009,089 bytes | 移到同隔离根的caches/ | 可重建且可恢复；后续运行可能重新生成 |
| 已移除的两项旧源码 | 39,276 bytes | 隔离根preservation-manifest.json中记录备份路径和hash | 未丢弃既有修改的唯一副本 |
| 3D延迟包gzip | 273,756 bytes | 223,839 bytes | 减少49,917 bytes，约18.2% |
| 默认2D初始JavaScript | 上轮228,815 bytes | 228,743 bytes | 保持既有延迟加载与预算 |

以上清理项合计使项目工作目录的对应内容减少约368.56MB；这是各项逻辑文件体积之和，不是磁盘剩余空间测量，也不代表测试生成新产物后的全目录净差。安装包已先核对官方SHA-256 `15ab698803f459444ec3e97ee52ab9f99db93a583819c7821b17dfcd7b4461e7`，已安装引擎、天气与运行依赖保留，清理后真实EnergyPlus回归仍通过。

永久删除安装ZIP被自动审批拒绝，返回`blocked by policy`，没有更具体理由。采用可恢复移动，不绕过拒绝做永久删除。隔离位置为 `P:/project-cleanup-quarantine-20261027-code/`，源码与缓存恢复清单分别为 `preservation-manifest.json`、`cache-manifest.json`。`styles-mi-home.before.css`保留旧装饰规则清理前副本。训练工程与2026-10-26隔离目录均未动。

## 保留与验证边界

保留 data/results、data/logs、data/private_memory、全部研究fixtures与原始实验记录、已安装运行时、后端环境以及有效前端依赖。不因为文件大、暂时无入口或属于研究脚本而直接删除。历史账本对已移除源码的提及保留为当时记录。

本轮审查覆盖前端调用/依赖、2D/3D可达性、构建上下文、路线图汇总和清理可恢复性；不宣称全仓逐行安全审计或已穷尽所有业务缺陷。没有改变实验指标、假设、解释策略、模型密钥或外部系统。

- 后端pytest 269/269；Ruff通过。
- 前端Vitest 17/17、Playwright 15/15、严格TypeScript、生产build与bundle门禁通过。
- Edge真实3D截图 `output/ui-cleanup-3d-20261027.png`，无页面脚本错误。
- 本地8000 `/health`为ok，EnergyPlus available/9区；`/api/agent/health`明确mock未验证真实连通。localhost默认80端口不可用，Docker daemon不可用；未部署。
- claim validator structurally_valid=true、submission_ready=false，RQ5独立人工审查仍阻塞。D7/E5保留物理校准/验证阻塞；有界只读research_claim_critic复核supportable。
- RAG及diff检查以本轮最终执行为准；机器清单 `output/project-cleanup-audit-20261027/summary.json`。
