"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authApi, ApiError } from "@/lib/api-client";

function PasswordResetConfirmForm() {
  const searchParams = useSearchParams();
  const tokenFromUrl = searchParams?.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (!tokenFromUrl) {
      setError("Reset token missing. Please use the link from your email.");
      return;
    }
    setLoading(true);
    try {
      await authApi.confirmPasswordReset(tokenFromUrl, password);
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  if (success) {
    return (
      <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
        <div className="w-full max-w-md text-center space-y-4">
          <div className="text-5xl">✅</div>
          <h1 className="text-2xl font-bold">Password updated</h1>
          <p className="text-muted-foreground">Your password has been changed successfully.</p>
          <Link
            href="/login"
            className="inline-block mt-2 px-6 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors"
          >
            Sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold">Set new password</h1>
          <p className="text-muted-foreground mt-2">Choose a strong password for your account.</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border bg-card p-8 shadow-sm space-y-5"
        >
          {error && (
            <div className="rounded-lg bg-destructive/10 border border-destructive/20 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {!tokenFromUrl && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">
              No reset token found. Please use the link from your email.
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm font-medium">
              New password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete="new-password"
              minLength={12}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min 12 characters"
              className="w-full h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition"
            />
            <p className="text-xs text-muted-foreground">Use at least 12 characters.</p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="confirm" className="text-sm font-medium">
              Confirm password
            </label>
            <input
              id="confirm"
              type="password"
              required
              autoComplete="new-password"
              minLength={12}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Repeat password"
              className="w-full h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition"
            />
          </div>

          <button
            type="submit"
            disabled={loading || !tokenFromUrl}
            className="w-full h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
          >
            {loading ? "Saving…" : "Set new password"}
          </button>

          <p className="text-center text-sm text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline font-medium">
              Back to sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

export default function PasswordResetConfirmPage() {
  return (
    <Suspense fallback={null}>
      <PasswordResetConfirmForm />
    </Suspense>
  );
}
