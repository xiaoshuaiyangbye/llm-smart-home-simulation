export type SceneViewMode = "3d" | "2d";

interface ViewModeToggleProps {
  value: SceneViewMode;
  onChange: (value: SceneViewMode) => void;
  onReset: () => void;
}

export function ViewModeToggle({ value, onChange, onReset }: ViewModeToggleProps) {
  return (
    <div className="view-mode-toggle" aria-label="户型视图切换">
      <button
        type="button"
        className={value === "3d" ? "active" : ""}
        onClick={() => onChange("3d")}
      >
        3D 俯瞰
      </button>
      <button
        type="button"
        className={value === "2d" ? "active" : ""}
        onClick={() => onChange("2d")}
      >
        2D 平面
      </button>
      <button type="button" className="secondary-button" onClick={onReset}>
        复位
      </button>
    </div>
  );
}
