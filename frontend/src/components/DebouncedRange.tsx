import { useEffect, useState } from "react";

interface DebouncedRangeProps {
  ariaLabel: string;
  disabled: boolean;
  max: number;
  min: number;
  onCommit: (value: number) => void;
  value: number;
}

/** Keeps slider feedback immediate while avoiding a request for every pointer pixel. */
export function DebouncedRange({ ariaLabel, disabled, max, min, onCommit, value }: DebouncedRangeProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);

  function commit(nextValue: number) {
    if (nextValue !== value) onCommit(nextValue);
  }

  return (
    <input
      aria-label={ariaLabel}
      type="range"
      min={min}
      max={max}
      value={draft}
      disabled={disabled}
      onChange={(event) => setDraft(Number(event.target.value))}
      onPointerUp={() => commit(draft)}
      onKeyUp={(event) => {
        if (["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) commit(draft);
      }}
      onBlur={() => commit(draft)}
    />
  );
}
