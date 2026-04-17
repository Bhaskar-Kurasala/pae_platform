import type { Metadata } from "next";
import Link from "next/link";
import { ChevronRight, Shield } from "lucide-react";
import { GradientMesh } from "@/components/ui/gradient-mesh";
import { MotionFade } from "@/components/ui/motion-fade";
import { PricingToggle } from "./_pricing-toggle";

export const metadata: Metadata = {
  title: "Pricing — PAE Platform",
  description: "Simple, transparent pricing. Start free. Upgrade when you're ready.",
};

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

const features = [
  // [feature label, free, pro, team]
  ["AI agents available", "3 agents", "All 20", "All 20"],
  ["Course lessons", "5 lessons", "18+ lessons", "18+ lessons + custom"],
  ["1-on-1 AI coaching sessions", false, true, true],
  ["Adaptive learning path", false, true, true],
  ["Spaced-repetition reviews", false, true, true],
  ["Mock interview agent", false, true, true],
  ["Portfolio builder agent", false, true, true],
  ["Progress analytics", "Basic", "Full dashboard", "Full dashboard"],
  ["Code review with ruff", false, true, true],
  ["Community access", true, true, true],
  ["Priority support", false, false, true],
  ["Team analytics dashboard", false, false, true],
  ["Custom curriculum", false, false, true],
  ["Team seats", "1", "1", "Up to 10"],
] as const;

const pricingFaqs = [
  {
    q: "Is there really a free tier?",
    a: "Yes — genuinely free, not a truncated trial. You get 3 AI agents, 5 real lessons, and community access forever with no credit card required.",
  },
  {
    q: "What payment methods do you accept?",
    a: "We accept all major credit cards (Visa, Mastercard, Amex) and PayPal. Payments are processed securely by Stripe. We never store your card details.",
  },
  {
    q: "How does the 30-day money-back guarantee work?",
    a: "If you are not satisfied within 30 days of your first Pro or Team payment, email us at billing@paeplatform.com and we will issue a full refund — no questions, no hassle.",
  },
  {
    q: "Can I switch between plans?",
    a: "Yes. Upgrades take effect immediately. Downgrades take effect at the end of your billing period. You will never be charged twice for the same period.",
  },
  {
    q: "Are annual discounts available?",
    a: "Yes — annual billing saves you 2 months (about 17% off). You can toggle between monthly and annual pricing on this page.",
  },
  {
    q: "Do you offer student or non-profit discounts?",
    a: "We offer a 50% discount for verified students and registered non-profit organisations. Email us at team@paeplatform.com with proof of eligibility.",
  },
] as const;

// ---------------------------------------------------------------------------
// Sub-component: Feature row cell
// ---------------------------------------------------------------------------

function Cell({ value }: { value: string | boolean }) {
  if (value === true) {
    return (
      <td className="px-4 py-3 text-center">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary/15 mx-auto">
          <span className="h-2 w-2 rounded-full bg-primary" aria-label="Included" />
        </span>
      </td>
    );
  }
  if (value === false) {
    return (
      <td className="px-4 py-3 text-center">
        <span className="text-sm text-muted-foreground" aria-label="Not included">—</span>
      </td>
    );
  }
  return (
    <td className="px-4 py-3 text-center text-sm text-muted-foreground">{value}</td>
  );
}

// ---------------------------------------------------------------------------
// Page (Server Component — toggle is a Client island)
// ---------------------------------------------------------------------------

export default function PricingPage() {
  return (
    <div className="overflow-x-hidden">
      {/* Hero */}
      <section className="relative overflow-hidden py-24 px-4">
        <GradientMesh />
        <MotionFade>
          <div className="max-w-2xl mx-auto text-center">
            <h1 className="text-[clamp(2rem,4vw,3rem)] font-bold tracking-tight mb-4">
              Simple, transparent pricing
            </h1>
            <p className="text-lg text-muted-foreground">
              Start free. Upgrade when you&apos;re ready.
            </p>
          </div>
        </MotionFade>
      </section>

      {/* Pricing cards with monthly/annual toggle (client island) */}
      <section aria-label="Pricing plans" className="max-w-5xl mx-auto px-4 mb-24">
        <PricingToggle />
      </section>

      {/* Feature comparison table */}
      <section
        aria-label="Plan feature comparison"
        className="max-w-5xl mx-auto px-4 mb-24"
      >
        <MotionFade>
          <h2 className="text-2xl font-bold text-center mb-8">Compare plans</h2>
        </MotionFade>
        <MotionFade delay={0.1}>
          <div className="rounded-xl border border-border overflow-hidden">
            <table className="w-full text-sm" role="table">
              <thead>
                <tr className="border-b border-border bg-muted/40">
                  <th className="px-4 py-3 text-left font-semibold text-foreground w-1/2">
                    Feature
                  </th>
                  <th className="px-4 py-3 text-center font-semibold text-foreground">Free</th>
                  <th className="px-4 py-3 text-center font-semibold text-primary">Pro</th>
                  <th className="px-4 py-3 text-center font-semibold text-foreground">Team</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {features.map(([label, free, pro, team]) => (
                  <tr key={label} className="hover:bg-muted/20 transition-colors">
                    <td className="px-4 py-3 text-sm text-foreground">{label}</td>
                    <Cell value={free} />
                    <Cell value={pro} />
                    <Cell value={team} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </MotionFade>
      </section>

      {/* Money-back guarantee badge */}
      <section
        aria-label="Money-back guarantee"
        className="max-w-xl mx-auto px-4 mb-24 text-center"
      >
        <MotionFade>
          <div className="inline-flex items-center gap-3 rounded-2xl border border-primary/30 bg-primary/5 px-6 py-4">
            <Shield className="h-6 w-6 text-primary shrink-0" aria-hidden="true" />
            <div className="text-left">
              <div className="text-sm font-semibold text-foreground">30-day money-back guarantee</div>
              <div className="text-xs text-muted-foreground mt-0.5">
                Not happy? Full refund within 30 days — no questions asked.
              </div>
            </div>
          </div>
        </MotionFade>
      </section>

      {/* FAQ */}
      <section
        aria-label="Pricing FAQ"
        className="max-w-3xl mx-auto px-4 pb-24"
      >
        <MotionFade>
          <h2 className="text-2xl font-bold text-center mb-8">Billing &amp; payment FAQ</h2>
        </MotionFade>
        <MotionFade delay={0.1}>
          <dl className="divide-y divide-border rounded-xl border border-border overflow-hidden">
            {pricingFaqs.map(({ q, a }) => (
              <details key={q} className="group">
                <summary
                  className="flex cursor-pointer items-center justify-between px-6 py-4 text-sm font-medium hover:bg-muted/50 transition-colors list-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/50 focus-visible:outline-none"
                >
                  <dt>{q}</dt>
                  <ChevronRight
                    className="h-4 w-4 text-muted-foreground shrink-0 transition-transform group-open:rotate-90"
                    aria-hidden="true"
                  />
                </summary>
                <dd className="px-6 pb-4 text-sm text-muted-foreground leading-relaxed">{a}</dd>
              </details>
            ))}
          </dl>
        </MotionFade>

        <MotionFade delay={0.2}>
          <div className="text-center mt-10">
            <p className="text-sm text-muted-foreground mb-3">
              Still have questions? We are happy to help.
            </p>
            <a
              href="mailto:team@paeplatform.com"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:text-primary/80 transition-colors"
            >
              Contact us <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </a>
          </div>
        </MotionFade>
      </section>
    </div>
  );
}
