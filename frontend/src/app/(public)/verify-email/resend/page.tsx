"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authApi, ApiError } from "@/lib/api-client";

function ResendVerificationForm() {
  const searchParams = useSearchParams();
  const prefillEmail = searchParams?.get("email") ?? "";

  const [email, setEmail] = useState(prefillEmail);
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.resendVerificationEmail(email);
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
            If <strong>{email}</strong> is registered and unverified, a new verification
            link has been sent. The link expires in 24 hours.
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
          <h1 className="text-3xl font-bold">Resend verification</h1>
          <p className="text-muted-foreground mt-2">
            Enter your email and we&apos;ll resend the verification link.
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
            {loading ? "Sending…" : "Resend verification email"}
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

export default function ResendVerificationPage() {
  return (
    <Suspense fallback={null}>
      <ResendVerificationForm />
    </Suspense>
  );
}
