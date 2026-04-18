import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MobileBottomNav } from "@/components/layouts/mobile-bottom-nav";

vi.mock("next/navigation", () => ({
  usePathname: () => "/today",
}));

describe("MobileBottomNav", () => {
  it("renders primary destinations as links", () => {
    render(<MobileBottomNav />);
    expect(screen.getByRole("link", { name: /today/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /courses/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /studio/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /tutor/i })).toBeInTheDocument();
  });

  it("marks the active route with aria-current=page", () => {
    render(<MobileBottomNav />);
    const today = screen.getByRole("link", { name: /today/i });
    expect(today).toHaveAttribute("aria-current", "page");
  });
});
