import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LandingPage from "@/app/(public)/page";

describe("LandingPage", () => {
  it("renders the platform heading", () => {
    render(<LandingPage />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/AI Engineering/i).length).toBeGreaterThan(0);
  });

  it("renders primary CTAs", () => {
    render(<LandingPage />);
    // Hero CTA uses "Start Free"; bottom CTA uses "Start for free" — both should link to /register.
    const registerLinks = screen.getAllByRole("link", { name: /start.*free/i });
    expect(registerLinks.length).toBeGreaterThan(0);
    expect(registerLinks[0]).toHaveAttribute("href", "/register");
  });

  it("surfaces the live demo anchor and platform stats", () => {
    render(<LandingPage />);
    // The hero secondary action jumps to the demo section.
    expect(screen.getByRole("link", { name: /try a live demo/i })).toBeInTheDocument();
    // Stats strip exposes an accessible label.
    expect(screen.getByRole("region", { name: /platform statistics/i })).toBeInTheDocument();
  });
});
