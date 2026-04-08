"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Bot, Brain, Code2, GitBranch, Zap } from "lucide-react";

const pipeline = [
  { icon: GitBranch, label: "GitHub Push", color: "text-[#1D9E75]" },
  { icon: Bot, label: "Content Agent", color: "text-[#7C3AED]" },
  { icon: Brain, label: "Curriculum Mapper", color: "text-[#1D9E75]" },
  { icon: Code2, label: "Code Review", color: "text-[#7C3AED]" },
  { icon: Zap, label: "Adaptive Quiz", color: "text-[#1D9E75]" },
];

export default function LandingPage() {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  function handleEmailCapture(e: React.FormEvent) {
    e.preventDefault();
    if (email) setSubmitted(true);
  }

  return (
    <div className="space-y-24 pb-24">
      {/* Hero */}
      <section className="max-w-6xl mx-auto px-4 pt-20 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/5 px-4 py-1.5 text-sm font-medium text-primary mb-6">
          <Zap className="h-3.5 w-3.5" aria-hidden="true" />
          18+ AI Agents • LangGraph • Claude API
        </div>
        <h1 className="text-4xl sm:text-6xl font-bold tracking-tight text-foreground leading-tight">
          Production{" "}
          <span className="text-primary">AI Engineering</span>
          <br />Platform
        </h1>
        <p className="mt-6 text-lg text-muted-foreground max-w-2xl mx-auto">
          Master GenAI systems engineering through hands-on projects, AI-powered tutoring,
          and real code reviews. From LangGraph to production deployment.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
          <Link
            href="/register"
            className="inline-flex items-center gap-2 h-11 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            Start Learning Free <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
          <Link
            href="/courses"
            className="inline-flex items-center gap-2 h-11 rounded-lg border border-border px-6 text-sm font-semibold hover:bg-muted transition-colors"
          >
            Browse Courses
          </Link>
        </div>
      </section>

      {/* Pipeline diagram */}
      <section className="max-w-6xl mx-auto px-4">
        <h2 className="text-center text-2xl font-bold mb-10">18+ AI Agents Working For You</h2>
        <div className="flex flex-wrap items-center justify-center gap-3">
          {pipeline.map(({ icon: Icon, label, color }, i) => (
            <div key={label} className="flex items-center gap-3">
              <div className="flex flex-col items-center gap-2 rounded-xl border bg-card p-5 shadow-sm w-32">
                <Icon className={`h-7 w-7 ${color}`} aria-hidden="true" />
                <span className="text-xs font-medium text-center leading-tight">{label}</span>
              </div>
              {i < pipeline.length - 1 && (
                <ArrowRight className="h-5 w-5 text-muted-foreground shrink-0" aria-hidden="true" />
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Free content CTA */}
      <section className="max-w-4xl mx-auto px-4">
        <div className="rounded-2xl border bg-card p-8 text-center shadow-sm">
          <h2 className="text-2xl font-bold mb-2">Free Course: LangGraph in Production</h2>
          <p className="text-muted-foreground mb-6">
            Hands-on exercises, AI code reviews, and a real capstone project — completely free.
          </p>
          <Link
            href="/courses"
            className="inline-flex items-center gap-2 h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            View Free Courses <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </section>

      {/* Email capture */}
      <section className="max-w-xl mx-auto px-4 text-center">
        <h2 className="text-2xl font-bold mb-2">Stay in the loop</h2>
        <p className="text-muted-foreground mb-6">New AI agent drops, course updates, and GenAI engineering insights.</p>
        {submitted ? (
          <p className="text-primary font-semibold">You&apos;re on the list! 🎉</p>
        ) : (
          <form onSubmit={handleEmailCapture} className="flex gap-2">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              aria-label="Email address"
              className="flex-1 h-10 rounded-lg border border-border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-primary/50"
            />
            <button
              type="submit"
              className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Subscribe
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
