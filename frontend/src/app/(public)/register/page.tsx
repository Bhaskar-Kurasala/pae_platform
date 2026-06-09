"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { ApiError, sanitizeNext } from "@/lib/api-client";

function RegisterForm() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [whatsappNumber, setWhatsappNumber] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const { register, isAuthenticated, _hasHydrated } = useAuthStore();
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = sanitizeNext(searchParams?.get("next") ?? null);
  const alreadyAuthedLanding = nextParam ?? "/today";

  useEffect(() => {
    if (_hasHydrated && isAuthenticated) {
      router.replace(alreadyAuthedLanding);
    }
  }, [_hasHydrated, isAuthenticated, router, alreadyAuthedLanding]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 12) {
      setError("Password must be at least 12 characters.");
      return;
    }
    setLoading(true);
    try {
      await register(email, fullName, password, whatsappNumber.trim() || undefined);
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
          <div className="text-5xl">📬</div>
          <h1 className="text-2xl font-bold">Check your inbox</h1>
          <p className="text-muted-foreground">
            We&apos;ve sent a verification link to <strong>{email}</strong>.
            Click it to activate your account, then{" "}
            <Link href="/login" className="text-primary hover:underline font-medium">
              log in
            </Link>
            .
          </p>
          <p className="text-xs text-muted-foreground">
            Didn&apos;t get it? Check your spam folder. The link expires in 24 hours.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold">Create your account</h1>
          <p className="text-muted-foreground mt-2">Start mastering production AI engineering</p>
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
            <label htmlFor="fullName" className="text-sm font-medium">
              Full name
            </label>
            <input
              id="fullName"
              type="text"
              required
              autoComplete="name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="Jane Doe"
              className="w-full h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition"
            />
          </div>

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
            <label htmlFor="password" className="text-sm font-medium">
              Password
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
            <label htmlFor="whatsappNumber" className="text-sm font-medium">
              WhatsApp number <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <input
              id="whatsappNumber"
              type="tel"
              autoComplete="tel"
              value={whatsappNumber}
              onChange={(e) => setWhatsappNumber(e.target.value)}
              placeholder="+919876543210"
              className="w-full h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50 transition"
            />
            <p className="text-xs text-muted-foreground">
              Lets the team reach out directly on WhatsApp if you go quiet. We never auto-message.
            </p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
          >
            {loading ? "Creating account…" : "Create account"}
          </button>

          <p className="text-center text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href="/login" className="text-primary hover:underline font-medium">
              Sign in
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
