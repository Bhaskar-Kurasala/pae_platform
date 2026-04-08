import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import LandingPage from "@/app/(public)/page";

describe("LandingPage", () => {
  it("renders the platform heading", () => {
    render(<LandingPage />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.getAllByText(/AI Engineering/i).length).toBeGreaterThan(0);
  });

  it("renders CTA buttons", () => {
    render(<LandingPage />);
    expect(screen.getByRole("link", { name: /get started/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /browse courses/i })).toBeInTheDocument();
  });
});
