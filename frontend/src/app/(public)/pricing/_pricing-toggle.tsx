"use client";

import { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface Tier {
  name: string;
  monthlyPrice: string;
  annualPrice: string;
  annualMonthly: string;
  highlight: boolean;
  badge?: string;
  features: readonly string[];
  cta: string;
  href: string;
}

const tiers: Tier[] = [
  {
    name: "Free",
    monthlyPrice: "$0",
    annualPrice: "$0",
    annualMonthly: "$0",
    highlight: false,
    features: [
      "3 AI agents",
      "5 lessons",
      "Community access",
      "Basic progress tracking",
    ],
    cta: "Start free",
    href: "/register",
  },
  {
    name: "Pro",
    monthlyPrice: "$29",
    annualPrice: "$290",
    annualMonthly: "$24",
    highlight: true,
    badge: "Most popular",
    features: [
      "All 20 AI agents",
      "All 18+ lessons",
      "1-on-1 AI coaching",
      "Portfolio builder agent",
      "Mock interview agent",
      "Adaptive learning path",
      "Priority support",
    ],
    cta: "Start Pro trial",
    href: "/register?plan=pro",
  },
  {
    name: "Team",
    monthlyPrice: "$99",
    annualPrice: "$990",
    annualMonthly: "$83",
    highlight: false,
    features: [
      "Everything in Pro",
      "Up to 10 seats",
      "Team analytics dashboard",
      "Custom curriculum",
      "Dedicated account manager",
    ],
    cta: "Contact sales",
    href: "/contact",
  },
];

export function PricingToggle() {
  const [annual, setAnnual] = useState(false);

  return (
    <div>
      {/* Toggle */}
      <div className="flex items-center justify-center gap-3 mb-10">
        <button
          type="button"
          onClick={() => setAnnual(false)}
          aria-pressed={!annual}
          className={cn(
            "text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded px-1",
            !annual ? "text-foreground" : "text-muted-foreground",
          )}
        >
          Monthly
        </button>

        {/* Toggle switch */}
        <button
          type="button"
          role="switch"
          aria-checked={annual}
          aria-label="Toggle annual billing"
          onClick={() => setAnnual((v) => !v)}
          className={cn(
            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none",
            annual ? "bg-primary" : "bg-muted",
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              "pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm ring-0 transition-transform",
              annual ? "translate-x-5" : "translate-x-0",
            )}
          />
        </button>

        <button
          type="button"
          onClick={() => setAnnual(true)}
          aria-pressed={annual}
          className={cn(
            "text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded px-1",
            annual ? "text-foreground" : "text-muted-foreground",
          )}
        >
          Annual
          <span className="ml-1.5 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
            2 months free
          </span>
        </button>
      </div>

      {/* Cards */}
      <div className="grid md:grid-cols-3 gap-6">
        {tiers.map(
          ({ name, monthlyPrice, annualPrice, annualMonthly, highlight, badge, features, cta, href }) => {
            const displayPrice = annual
              ? name === "Free"
                ? "$0"
                : annualMonthly
              : monthlyPrice;

            const subLabel = annual && name !== "Free"
              ? `$${annualPrice.replace("$", "")} billed annually`
              : name === "Free"
              ? "Forever free"
              : "per month";

            return (
              <div
                key={name}
                className={cn(
                  "rounded-2xl border p-6 flex flex-col h-full transition-shadow hover:shadow-md",
                  highlight
                    ? "border-primary bg-primary/5 shadow-sm"
                    : "border-border bg-card",
                )}
              >
                <div className="mb-5">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-base font-semibold">{name}</span>
                    {badge && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        {badge}
                      </span>
                    )}
                  </div>
                  <div className="flex items-end gap-1">
                    <span className="text-3xl font-bold">{displayPrice}</span>
                    {name !== "Free" && (
                      <span className="text-sm text-muted-foreground mb-1">/mo</span>
                    )}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">{subLabel}</div>
                </div>

                <ul className="space-y-2 mb-6 flex-1" role="list">
                  {features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full bg-primary/15 flex items-center justify-center">
                        <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
                      </span>
                      {f}
                    </li>
                  ))}
                </ul>

                <Link
                  href={href}
                  className={cn(
                    "inline-flex h-10 items-center justify-center rounded-lg text-sm font-semibold transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none",
                    highlight
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "border border-border hover:bg-muted",
                  )}
                >
                  {cta}
                </Link>
              </div>
            );
          },
        )}
      </div>
    </div>
  );
}
