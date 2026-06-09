"use client";

import { useState } from "react";
import Link from "next/link";
import { authApi, ApiError } from "@/lib/api-client";

export default function PasswordResetRequestPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.requestPasswordReset(email);
      setSubmitted(true);
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

  if (submitted) {
    return (
      <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
        <div className="w-full max-w-md text-center space-y-4">
          <div className="text-5xl">📬</div>
          <h1 className="text-2xl font-bold">Check your inbox</h1>
          <p className="text-muted-foreground">
            If <strong>{email}</strong> is registered, a password reset link has been sent.
            The link expires in 1 hour.
          </p>
          <p className="text-sm text-muted-foreground">
            Didn&apos;t get it? Check your spam folder.{" "}
            <button
              onClick={() => { setSubmitted(false); setEmail(""); }}
              className="text-primary hover:underline font-medium"
            >
              Try again
            </button>
          </p>
          <p className="text-sm text-muted-foreground">
            <Link href="/login" className="text-primary hover:underline font-medium">
              Back to sign in
            </Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold">Reset your password</h1>
          <p className="text-muted-foreground mt-2">
            Enter your email and we&apos;ll send a reset link if it&apos;s registered.
          </p>
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

          <button
            type="submit"
            disabled={loading}
            className="w-full h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
          >
            {loading ? "Sending…" : "Send reset link"}
          </button>

          <p className="text-center text-sm text-muted-foreground">
            Remembered it?{" "}
            <Link href="/login" className="text-primary hover:underline font-medium">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
