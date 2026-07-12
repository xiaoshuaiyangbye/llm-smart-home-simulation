import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { DebouncedRange } from "./DebouncedRange";

test("commits the slider value only after interaction completes", () => {
  const onCommit = vi.fn();
  render(<DebouncedRange ariaLabel="亮度" disabled={false} min={0} max={100} value={40} onCommit={onCommit} />);

  const slider = screen.getByLabelText("亮度");
  fireEvent.change(slider, { target: { value: "75" } });
  expect(onCommit).not.toHaveBeenCalled();

  fireEvent.pointerUp(slider);
  expect(onCommit).toHaveBeenCalledWith(75);
});
