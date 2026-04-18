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
  isAuthenticated: boolean;
  _hasHydrated: boolean;
  setAuth: (user: User, token: string) => void;
  clearAuth: () => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, fullName: string, password: string) => Promise<void>;
  logout: () => void;
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

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      _hasHydrated: false,

      setHasHydrated: (v) => set({ _hasHydrated: v }),
      setAuth: (user, token) => set({ user, token, isAuthenticated: true }),
      clearAuth: () => set({ user: null, token: null, isAuthenticated: false }),

      login: async (email, password) => {
        const tokens = await authApi.login({ email, password });
        set({ token: tokens.access_token, isAuthenticated: true });
        const userResp = await authApi.me();
        set({ user: toUser(userResp) });
      },

      register: async (email, fullName, password) => {
        await authApi.register({ email, full_name: fullName, password });
        const tokens = await authApi.login({ email, password });
        set({ token: tokens.access_token, isAuthenticated: true });
        const userResp = await authApi.me();
        set({ user: toUser(userResp) });
      },

      logout: () => set({ user: null, token: null, isAuthenticated: false }),
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({
        user: state.user,
        token: state.token,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    },
  ),
);
