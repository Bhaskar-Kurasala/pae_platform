"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { authApi, type UserResponse } from "@/lib/api-client";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: "student" | "admin" | "instructor";
  avatar_url?: string;
}

interface AuthState {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  _hasHydrated: boolean;
  setAuth: (user: User, token: string, refreshToken: string) => void;
  clearAuth: () => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, fullName: string, password: string) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<boolean>;
  setHasHydrated: (v: boolean) => void;
}

function toUser(r: UserResponse): User {
  return {
    id: r.id,
    email: r.email,
    full_name: r.full_name,
    role: r.role as User["role"],
    avatar_url: r.avatar_url,
  };
}

// Mirror the user's role into a cookie so Next.js edge middleware can gate
// /admin/* without reading localStorage. Cookie is short-lived, non-HttpOnly,
// SameSite=Lax — purely a presentation hint; the backend remains the
// authoritative gate (returns 403 on token-role mismatch).
const ROLE_COOKIE = "pae_role";
function setRoleCookie(role: User["role"] | null): void {
  if (typeof document === "undefined") return;
  if (role) {
    // 12h horizon — a bit longer than the access token, refreshed on every
    // login. SameSite=Lax so it's sent on top-level admin navigations.
    document.cookie = `${ROLE_COOKIE}=${role}; Path=/; Max-Age=43200; SameSite=Lax`;
  } else {
    document.cookie = `${ROLE_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`;
  }
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      refreshToken: null,
      isAuthenticated: false,
      _hasHydrated: false,

      setHasHydrated: (v) => {
        set({ _hasHydrated: v });
        // After rehydrating from localStorage, replay the cookie so the
        // middleware sees the right role on the next request.
        const state = get();
        setRoleCookie(state.isAuthenticated ? state.user?.role ?? null : null);
      },
      setAuth: (user, token, refreshToken) => {
        set({ user, token, refreshToken, isAuthenticated: true });
        setRoleCookie(user.role);
      },
      clearAuth: () => {
        set({ user: null, token: null, refreshToken: null, isAuthenticated: false });
        setRoleCookie(null);
      },

      login: async (email, password) => {
        const tokens = await authApi.login({ email, password });
        set({
          token: tokens.access_token,
          refreshToken: tokens.refresh_token,
          isAuthenticated: true,
        });
        try {
          const userResp = await authApi.me();
          const user = toUser(userResp);
          set({ user });
          setRoleCookie(user.role);
        } catch (err) {
          // If /me fails we have a zombie-auth state — roll back so guards
          // don't hang on an infinite spinner (DISC-52).
          set({
            user: null,
            token: null,
            refreshToken: null,
            isAuthenticated: false,
          });
          setRoleCookie(null);
          throw err;
        }
      },

      register: async (email, fullName, password) => {
        await authApi.register({ email, full_name: fullName, password });
        const tokens = await authApi.login({ email, password });
        set({
          token: tokens.access_token,
          refreshToken: tokens.refresh_token,
          isAuthenticated: true,
        });
        try {
          const userResp = await authApi.me();
          const user = toUser(userResp);
          set({ user });
          setRoleCookie(user.role);
        } catch (err) {
          set({
            user: null,
            token: null,
            refreshToken: null,
            isAuthenticated: false,
          });
          setRoleCookie(null);
          throw err;
        }
      },

      logout: () => {
        set({
          user: null,
          token: null,
          refreshToken: null,
          isAuthenticated: false,
        });
        setRoleCookie(null);
      },

      refreshMe: async () => {
        const token = get().token;
        if (!token) return false;
        try {
          const userResp = await authApi.me();
          const user = toUser(userResp);
          set({ user });
          setRoleCookie(user.role);
          return true;
        } catch {
          set({
            user: null,
            token: null,
            refreshToken: null,
            isAuthenticated: false,
          });
          setRoleCookie(null);
          return false;
        }
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        refreshToken: state.refreshToken,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);

// Cross-tab logout sync (DISC-12): when another tab clears auth-storage or
// writes a cleared state, mirror it into this tab's in-memory store.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== "auth-storage") return;
    const store = useAuthStore.getState();
    if (e.newValue === null) {
      // key removed → cleared elsewhere
      if (store.isAuthenticated) store.clearAuth();
      return;
    }
    try {
      const parsed = JSON.parse(e.newValue) as {
        state?: { isAuthenticated?: boolean; token?: string | null };
      };
      const incomingAuthed = parsed.state?.isAuthenticated === true && !!parsed.state?.token;
      if (!incomingAuthed && store.isAuthenticated) {
        store.clearAuth();
        setRoleCookie(null);
      }
    } catch {
      // ignore parse errors
    }
  });
}
