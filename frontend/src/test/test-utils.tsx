import { render as rtlRender, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";

/**
 * Render a component inside the providers it needs in tests.
 *
 * Components rendered in the v8 shell (e.g. TutorScreen → useDueCards) call
 * `useQuery`, which throws without a QueryClientProvider. This helper supplies a
 * fresh, retry-disabled QueryClient per render so component tests don't need to
 * wire one up by hand. It is a drop-in for `@testing-library/react`'s `render`:
 * import `render` from this module instead.
 */
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  return rtlRender(ui, { wrapper: Wrapper, ...options });
}

// Re-export the rest of the testing-library API, then override `render` with the
// provider-wrapped version so existing `render(...)` call sites keep working.
export * from "@testing-library/react";
export { renderWithProviders as render };
