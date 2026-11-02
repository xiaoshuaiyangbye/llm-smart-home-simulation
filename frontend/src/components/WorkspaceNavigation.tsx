export const workspacePages = {
  overview: { label: "住宅总览", description: "先看空间，再看当前房间的状态。", icon: "⌂" },
  devices: { label: "设备控制", description: "选择房间，直接调节灯光、温度和通风。", icon: "⊞" },
  assistant: { label: "家庭助手", description: "说出需要，查看助手执行了什么。", icon: "✧" },
  automation: { label: "自动运行", description: "管理自动控制、生活推演与个人偏好。", icon: "↻" },
  experiments: { label: "物理实验", description: "用 EnergyPlus 创建全屋实验，查看分房间结果。", icon: "⌁" },
  data: { label: "状态与趋势", description: "查看生活模拟的环境、设备能耗与变化记录。", icon: "▥" },
} as const;

export type WorkspacePage = keyof typeof workspacePages;

export function WorkspaceNavigation({ active, onNavigate }: { active: WorkspacePage; onNavigate: (page: WorkspacePage) => void }) {
  return <aside className="home-nav" aria-label="住宅中控导航">
    <button type="button" className="nav-home" onClick={() => onNavigate("overview")} aria-label="返回住宅总览">
      <span className="workspace-logo" aria-hidden="true">⌂</span><span className="nav-home-copy"><strong>栖居</strong><small>智能住宅仿真</small></span>
    </button>
    <p className="nav-group-label">我的工作空间</p>
    <nav aria-label="功能页面">{Object.entries(workspacePages).map(([key, page]) => <button
      type="button" key={key} className={active === key ? "active" : ""} aria-current={active === key ? "page" : undefined}
      onClick={() => onNavigate(key as WorkspacePage)}><span className="workspace-nav-icon" aria-hidden="true">{page.icon}</span>{page.label}</button>)}</nav>
    <a href="http://127.0.0.1:8014/local-v3/" target="_blank" rel="noopener noreferrer" className="local-model-integration-link" style={{ display: "block", margin: "16px", fontSize: "13px" }}>本地模型联调（隔离仿真）↗</a>
    <div className="nav-footnote"><span className="nav-resident">R1</span><div><strong>本地住户空间</strong><small>软件仿真 · 非真实设备</small></div></div>
  </aside>;
}
