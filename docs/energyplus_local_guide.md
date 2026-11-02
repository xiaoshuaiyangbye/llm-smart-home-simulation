# 本地 EnergyPlus 全屋实验工作台

## 当前版本：设计户型的九空间接入（2026-10-27）

新建作业默认 `spatial_scope=whole_home`，覆盖客厅、卧室、书房、餐厅、厨房、卫生间、洗衣区、阳台和走廊，共 97.53 m²。九个空间在同一个 EnergyPlus 26.2.0 引擎中运行；每个空间独立记录温度、湿度、CO₂、照度、控制和模拟电量。

空间权威文件为 `data/energyplus/home_layout.json`：依据 `frontend/src/data/floorPlan.ts` 的墙线修正显示矩形重叠、走廊轮廓和外墙缺口；主界面的 2D/3D 地面、房间定位与 EnergyPlus 共用多边形。层高暂用 3 m；餐厅/走廊采用 `Construction:AirBoundary`，不是实体隔墙。相邻实墙双面配对传热；客餐厅、餐厨与餐厅/走廊使用声明的固定双向混合流量，其他门暂视为关闭。阳台依现有玻璃设计作封闭热区。这些是明确记录的建模假设，不是现场测绘。

设备按 `backend/app/config/devices.yaml` 映射：九房间照明、已有四房间 HVAC/机械通风，以及实际外窗对应的自然通风。各外窗单独使用几何面积和墙面法向；窗高暂设 1.5 m。没有空调的房间不增设 HVAC；餐厅/走廊没有设计外窗，因此其配置窗户动作被明确拒绝；窗帘尚无物理执行器。风扇目前映射机械换气，不代表人体风速舒适度。

界面可选择当前房间、查看全屋及每房间结果，切换房间时序并下载 `whole_home.epJSON`、`spatial_bindings.json`、`observations.csv`、`accounting_audit.json` 和 SQL。手动设定默认作用于所有房间已有设备；API `manual_room_controls` 可按房间覆盖。灯具校准仅用于当前所选房间，不能把一个测量点的拟合推广到全屋。

当前合成占用：所选 `current_room_id` 在 08:00–18:00 为两人，其余房间无人；不是住户移动或现场占用数据。无人房间的占用目标满足率为 `null`，界面显示不适用。建筑材料、灯具功率/照度、COP、地面 18°C 默认温度、气流与气候均未实测校准。

```powershell
backend/.venv/Scripts/python.exe scripts/run_energyplus_experiment.py --controllers rule harness_mock --season summer
backend/.venv/Scripts/python.exe scripts/run_energyplus_experiment.py --controllers rule harness_mock --season winter
```

最终产物：`data/results/energyplus/comparisons/whole-home-summer-20261027-v2/comparison.json` 和 `whole-home-winter-20261027-v2/comparison.json`。各为规则/mock两个单日作业，每作业 288 时间点、2592 room samples、0 severe、区间房间/全屋电量残差 0 J，配对模型/天气/初态指纹一致。v2 修复了全屋护栏数组漏记，并按外窗几何生成通风；此前同名无 v2 产物保留为开发记录。它们不是多次独立重复，也没有完成真实 DeepSeek 全屋实验。

SQL `Zone Timestep` 是能耗权威值。房间 `Electricity:Zone` 不包含全部 Ideal Loads HVAC 电量，须加上该房间 SQL heating/cooling fuel energy 后再与 `Electricity:Facility` 核对；热量与电量分别保留。原始 API 回调可能只对应末个 HVAC 子步，保存在 `raw_callback_observations.jsonl`，不可冒充区间总量。

本轮使用 Edge 实际提交全屋作业、验证九行结果及房间切换，截图 `output/energyplus-whole-home-panel.png`、`output/energyplus-whole-home-mobile.png`，记录 `output/energyplus-whole-home-browser.json`。验证时本地后端 8000 `/health` 为 ok，`/api/agent/health` 明确报告 mock 无真实模型连通验证；DeepSeek 端点未就绪。网页入口仍为 <http://127.0.0.1:5173/>，启动方式见下方历史说明。

历史单房间可用 `--spatial-scope single_room` 显式复现。历史 2026-10-26 DeepSeek 数字仅代表单房间，不适用于全屋；旧结果不删除，也不与全屋结果直接比较。当前主界面的普通生活模拟仍使用原模拟器；全屋 EnergyPlus 运行在独立物理实验工作台中。

## 历史接入记录：2026-10-26 单房间示例

以下单房间尺寸、结果与服务启动记录均为历史信息；运行状态以重新探测为准。


## 打开

本轮已在本机启动以下 loopback 服务：

- 前端：<http://127.0.0.1:5173/>
- FastAPI：<http://127.0.0.1:8000/>
- EnergyPlus 状态：<http://127.0.0.1:8000/api/energyplus/status>
- 本地 DeepSeek 规划器：<http://127.0.0.1:8011/health>

首页向下展开“EnergyPlus 单房间物理仿真实验”。可选择规则、手动、Harness mock 或训练后的 DeepSeek Harness，提交后查看环境时序、研究指标、动作追踪、来源和账目，并下载相关文件。

## 运行依赖

- 引擎：官方 EnergyPlus 26.2.0 Windows x86_64，安装于 `.runtime/energyplus/`，官方资产 SHA-256 在 `.runtime/energyplus/installation.json`。
- 房间：来源见 `data/energyplus/references/source.json`；从官方 1ZoneUncontrolled 示例派生为 5×4×3 m 单房间并增加南向窗、灯、理想负荷 HVAC、机械/自然通风与 CO₂ 平衡。
- 天气：随 EnergyPlus 安装的 Golden NREL TMY3 EPW，SHA-256 随每次运行写入来源记录。
- 服务：后端 8000，Vite 前端 5173，训练工程的本地模型规划器 8011。它们均绑定 loopback；现有总系统代理仍设为 `LLM_MODE=mock`，避免替换旧入口或与单独训练环境混用。
- 结果：`data/results/energyplus/workbench/<run_id>/`；比较报告位于 `data/results/energyplus/comparisons/<id>/comparison.json`。

## PowerShell 启动

如果本轮后台进程已退出，在仓库根目录分别启动服务。后端、前端窗口可继续保持运行；模型服务只在配对训练/评测完成后才会加载权重。

```powershell
$env:LLM_MODE = 'mock'
Set-Location P:/llm-smart-home-simulation/backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location P:/llm-smart-home-simulation/frontend
../.runtime/node-v22.16.0-win-x64/node.exe node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
```

```powershell
Set-Location P:/smart-home-model-training
./.venv/Scripts/python.exe src/local_finetune/serve.py --port 8011
```

只要调用本地模型，它会加载 4bit 基座和 LoRA adapter；等配对评测状态变为 `completed` 后，EnergyPlus 页面的 DeepSeek 选项才启用。

## 配对对照

```powershell
Set-Location P:/llm-smart-home-simulation
backend/.venv/Scripts/python.exe scripts/run_energyplus_experiment.py --controllers rule harness_mock --season summer --days 1
```

可把 `harness_real` 加入控制器列表；训练/评测未完成或模型端点不可用时会显式失败。默认一日包含 288 个五分钟样本。控制间隔必须为五分钟整数倍，每次最多七天。取消为协作式，worker 在下一回调停止。

## 结果口径与限制

- SQL 中排除 warmup 的 `Zone Timestep` 结果是每个能耗区间的权威数据；电量、照明、制冷/制热电量与热负荷各自保留单位和字段。
- CO₂ 表示充分混合单区质量平衡，不是 PM2.5 或 VOC 测量。自然采光是单个桌面参考点，灯光照度是经验默认或用户声明的点位拟合。
- 当前单房间、Golden 天气、占用日程、Ideal Loads 与照明响应未由用户设备/建筑实验校准。控制器间单日结果只作描述性软件仿真；目标满足率不匹配时不得宣称节能优越。
- 校准 JSON 需要至少 6 个实测点和 3 个不同调光档位，并由提交者明确确认环境光已扣除；留出集只检验交替测量点的拟合，不证明全屋照度分布或仪表准确性。
- DeepSeek adapter 使用合成软件标签训练，未经过独立人工语义审查；Harness 中模型只提供候选工具动作，系统继续经过已有语义、安全与动作映射检查。该路径目前是 hybrid DeepSeek proposal + existing mock-semantics stages，不等于各 Harness agent 都由 DeepSeek 驱动。
- 当前本机证据：200 条合成留出集 adapter JSON schema-valid 为 100%，完全匹配有序工具调用为 91%；真实 EnergyPlus 夏季一天运行包含 48 次 DeepSeek 调用，输出 48 个灯具动作并通过现有动作能力映射。该开灯任务的 configured occupancy comfort satisfaction 为 0%，CO₂ 超限 2941.8 ppm·min，模拟电量 4.974 kWh；同初态 rule 为 90%、0 ppm·min、2.699 kWh。用户请求只是开灯，但评分还包含温度/CO₂，因此该比较暴露模型未维持系统全局目标，不作方法优劣或节能推断。指令诊断原始结论在 `data/results/energyplus/model_diagnostics/20261026.json`。
- 指令级诊断已观察到失败：一个空调 24°C 输入生成了 `mode=off`；一个复合舒适/通风指令输出的 plan/tool call 数量不符而被本地服务拒绝。简单开灯及简化状态下的部分复合命令能返回合法动作，也不足以证明泛化正确性。应将这些反例纳入后续真实模型语义测试集。
- Harness 起始设备状态为 HVAC/灯/风扇/窗户关闭；EnergyPlus 的 warmup schedule 单独使用，避免把 warmup 值冒充仿真控制初态。
