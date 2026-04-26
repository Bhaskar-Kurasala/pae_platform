import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TailoredResumeQuotaChip } from "../quota-chip";

vi.mock("@/lib/api-client", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
}));

import { api } from "@/lib/api-client";

function renderWithQuery(ui: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("TailoredResumeQuotaChip", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows the 'first resume free' label on first use", async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      quota: {
        allowed: true,
        reason: "first_resume_free",
        remaining_today: 5,
        remaining_month: 20,
        reset_at: null,
      },
    });

    renderWithQuery(<TailoredResumeQuotaChip />);

    await waitFor(() => {
      expect(screen.getByText(/first resume free/i)).toBeInTheDocument();
    });
  });

  it("shows the daily-blocked label when out of quota", async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      quota: {
        allowed: false,
        reason: "daily_limit",
        remaining_today: 0,
        remaining_month: 12,
        reset_at: "2026-04-26T00:00:00Z",
      },
    });

    renderWithQuery(<TailoredResumeQuotaChip />);

    await waitFor(() => {
      expect(screen.getByText(/today's free limit/i)).toBeInTheDocument();
    });
  });

  it("shows the within-quota counter when partially used", async () => {
    (api.get as ReturnType<typeof vi.fn>).mockResolvedValue({
      quota: {
        allowed: true,
        reason: "within_quota",
        remaining_today: 3,
        remaining_month: 18,
        reset_at: null,
      },
    });

    renderWithQuery(<TailoredResumeQuotaChip />);

    await waitFor(() => {
      // 5 - 3 = 2 used today
      expect(screen.getByText(/2 of 5 today/i)).toBeInTheDocument();
    });
  });
});
