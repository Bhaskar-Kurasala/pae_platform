import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LandingPage from "@/app/(public)/page";

describe("LandingPage", () => {
  it("renders the platform heading", () => {
    render(<LandingPage />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/AI Engineering/i).length).toBeGreaterThan(0);
  });

  it("renders CTA links", () => {
    render(<LandingPage />);
    // "Start Learning Free" is the primary CTA
    expect(screen.getByRole("link", { name: /start learning free/i })).toBeInTheDocument();
    // "Browse Courses" appears multiple times — just confirm at least one exists
    expect(screen.getAllByRole("link", { name: /browse courses/i }).length).toBeGreaterThan(0);
  });

  it("renders email capture form", () => {
    render(<LandingPage />);
    expect(screen.getByRole("textbox", { name: /email address/i })).toBeInTheDocument();
  });
});
