# Real runtime Implementation Plan

**Goal:** 在线应用禁止 mock，语义调用真实 Qwen，EnergyPlus 真实规划同时使用真实语义。
**Architecture:** 在线 API 拒绝 mock 配置和控制器；离线历史对照保持可复现。模型失败明确失败。
**Tech Stack:** FastAPI, React, Ollama, local DeepSeek, EnergyPlus.

## Global Constraints

保留既有修改、历史产物与测试夹具；不改变研究指标；不提交或推送。

### Task 1: 在线运行链路

- [x] 修改 main.py 在线运行配置门禁、EnergyPlus API 与两个控制器的真实语义路径，移除 UI mock 选项。
- [x] 添加配置拒绝及真实路径回归；pytest20 passed、Ruff、Vitest17 passed、前端 build通过。
- [x] 启动本地真实模型，重启 API；真实health与控制指令成功；浏览器确认无mock选项；记录 backlog 与边界。DeepSeek训练未完成，未执行真实物理模型配对。
