"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { ApiError, sanitizeNext } from "@/lib/api-client";

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [errorKind, setErrorKind] = useState<"default" | "locked" | "unverified">("default");
  const [loading, setLoading] = useState(false);
  const { login, isAuthenticated, user, _hasHydrated } = useAuthStore();
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = sanitizeNext(searchParams?.get("next") ?? null);
  const roleLanding =
    user?.role === "admin" || user?.role === "instructor" ? "/admin" : "/today";
  const landing = nextParam ?? roleLanding;

  useEffect(() => {
    if (_hasHydrated && isAuthenticated) {
      router.replace(landing);
    }
  }, [_hasHydrated, isAuthenticated, router, landing]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setErrorKind("default");
    setLoading(true);
    try {
      await login(email, password);
      const fresh = useAuthStore.getState().user;
      const postLoginLanding =
        nextParam ??
        (fresh?.role === "admin" || fresh?.role === "instructor" ? "/admin" : "/today");
      router.replace(postLoginLanding);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 423) {
          setErrorKind("locked");
          setError(err.message);
        } else if (err.status === 403 && err.message.includes("not verified")) {
          setErrorKind("unverified");
          setError(err.message);
        } else {
          setError(err.message);
        }
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold">Welcome back</h1>
          <p className="text-muted-foreground mt-2">Sign in to continue learning</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border bg-card p-8 shadow-sm space-y-5"
        >
          {error && (
            <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive space-y-1">
              <p>{error}</p>
              {errorKind === "unverified" && (
                <p>
                  <Link
                    href={`/verify-email/resend?email=${encodeURIComponent(email)}`}
                    className="underline font-medium hover:text-destructive/80"
                  >
                    Resend verification email
                  </Link>
                </p>
              )}
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition"
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="password" className="text-sm font-medium">
                Password
              </label>
              <Link
                href="/password-reset/request"
                className="text-xs text-muted-foreground hover:text-primary transition-colors"
              >
                Forgot password?
              </Link>
            </div>
            <input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition"
            />
          </div>

          <button
            type="submit"
            disabled={loading || errorKind === "locked"}
            className="w-full h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>

          <p className="text-center text-sm text-muted-foreground">
            No account?{" "}
            <Link href="/register" className="text-primary hover:underline font-medium">
              Register free
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
