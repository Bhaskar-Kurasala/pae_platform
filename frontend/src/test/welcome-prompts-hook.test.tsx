/**
 * useWelcomePrompts hook — verifies:
 *  - returns the curated FALLBACK when not authenticated (or before query lands)
 *  - merges API prompts with the FALLBACK shape so consumers always get an array
 */
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useWelcomePrompts } from "@/lib/hooks/use-welcome-prompts";

const mockChatApi = vi.hoisted(() => ({
  welcomePrompts: vi.fn(),
}));

vi.mock("@/lib/chat-api", () => ({
  chatApi: mockChatApi,
}));

let isAuthed = true;
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (selector: (s: { isAuthenticated: boolean }) => unknown) =>
    selector({ isAuthenticated: isAuthed }),
}));

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

describe("useWelcomePrompts", () => {
  it("returns the fallback prompt set when unauthenticated", () => {
    isAuthed = false;
    const { result } = renderHook(() => useWelcomePrompts("auto"), {
      wrapper: wrap(),
    });
    expect(result.current.data.prompts.length).toBeGreaterThanOrEqual(4);
    expect(result.current.data.prompts[0]?.text).toBeTruthy();
  });

  it("uses API data when the hook resolves", async () => {
    isAuthed = true;
    mockChatApi.welcomePrompts.mockResolvedValueOnce({
      mode: "tutor",
      prompts: [
        {
          text: "Walk me through async/await",
          icon: "🎓",
          kind: "tutor",
          rationale: "last_lesson",
        },
      ],
    });
    const { result } = renderHook(() => useWelcomePrompts("tutor"), {
      wrapper: wrap(),
    });
    await waitFor(() =>
      expect(result.current.data.prompts[0]?.rationale).toBe("last_lesson"),
    );
    expect(result.current.data.prompts[0]?.text).toBe(
      "Walk me through async/await",
    );
  });
});
