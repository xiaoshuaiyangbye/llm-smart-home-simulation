import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceNavigation } from "./WorkspaceNavigation";

describe("isolated local model navigation", () => {
  it("links to the opt-in overlay without changing the current page", () => {
    const onNavigate = vi.fn();
    render(<WorkspaceNavigation active="overview" onNavigate={onNavigate} />);
    const link = screen.getByRole("link", { name: /本地模型联调/ });
    expect(link.getAttribute("href")).toBe("http://127.0.0.1:8014/local-v3/");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
