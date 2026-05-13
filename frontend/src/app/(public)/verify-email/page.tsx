"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authApi, ApiError } from "@/lib/api-client";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams?.get("token") ?? "";

  const [status, setStatus] = useState<"verifying" | "success" | "error">(
    token ? "verifying" : "error"
  );
  const [errorMessage, setErrorMessage] = useState(
    token ? "" : "No verification token found. Please use the link from your email."
  );

  useEffect(() => {
    if (!token) return;
    authApi
      .verifyEmail(token)
      .then(() => setStatus("success"))
      .catch((err) => {
        setErrorMessage(
          err instanceof ApiError ? err.message : "Verification failed. Please try again."
        );
        setStatus("error");
      });
  }, [token]);

  if (status === "verifying") {
    return (
      <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
        <div className="w-full max-w-md text-center space-y-4">
          <div className="text-5xl animate-pulse">🔐</div>
          <h1 className="text-2xl font-bold">Verifying your email…</h1>
          <p className="text-muted-foreground">Just a moment.</p>
        </div>
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center px-4">
        <div className="w-full max-w-md text-center space-y-4">
          <div className="text-5xl">✅</div>
          <h1 className="text-2xl font-bold">Email verified!</h1>
          <p className="text-muted-foreground">
            Your account is now active. Sign in to start learning.
          </p>
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
      <div className="w-full max-w-md text-center space-y-4">
        <div className="text-5xl">❌</div>
        <h1 className="text-2xl font-bold">Verification failed</h1>
        <p className="text-muted-foreground">{errorMessage}</p>
        <p className="text-sm text-muted-foreground">
          Need a new link?{" "}
          <Link href="/login" className="text-primary hover:underline font-medium">
            Sign in
          </Link>{" "}
          and we&apos;ll offer to resend it.
        </p>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailContent />
    </Suspense>
  );
}
