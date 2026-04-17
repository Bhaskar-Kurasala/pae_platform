import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  Brain,
  Briefcase,
  ChevronRight,
  Code2,
  GitBranch,
  GitMerge,
  Layers,
  LineChart,
  MessageSquare,
  Network,
  Repeat2,
  Search,
  Sparkles,
  Star,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import { SectionHero } from "@/components/ui/section-hero";
import { MotionFade } from "@/components/ui/motion-fade";
import { GradientMesh } from "@/components/ui/gradient-mesh";
import { cn } from "@/lib/utils";
import { DemoWidget } from "./_components/demo-widget";

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

const agents = [
  // Creation (teal)
  { name: "Content Ingestion", icon: GitBranch, desc: "Processes GitHub pushes and YouTube videos into course content", category: "creation" },
  { name: "Curriculum Mapper", icon: Layers, desc: "Maps content metadata to structured learning paths", category: "creation" },
  { name: "MCQ Factory", icon: Sparkles, desc: "Generates quiz questions with distractors from any lesson", category: "creation" },
  { name: "Coding Assistant", icon: Code2, desc: "PR-style inline code feedback and debugging help", category: "creation" },
  { name: "Student Buddy", icon: MessageSquare, desc: "TL;DR and ELI5 explanations in under 200 words", category: "creation" },
  { name: "Deep Capturer", icon: Network, desc: "Weekly synthesis connecting concepts across lessons", category: "creation" },
  // Learning (teal)
  { name: "Socratic Tutor", icon: Search, desc: "Guides understanding through questions, never just answers", category: "learning" },
  { name: "Spaced Repetition", icon: Repeat2, desc: "SM-2 algorithm scheduling your next review at the perfect time", category: "learning" },
  { name: "Knowledge Graph", icon: Network, desc: "Visualizes your skill mastery across every concept", category: "learning" },
  { name: "Adaptive Path", icon: GitMerge, desc: "Personalizes your lesson order based on quiz scores", category: "learning" },
  // Analytics (gray)
  { name: "Adaptive Quiz", icon: Brain, desc: "Adjusts question difficulty in real-time as you answer", category: "analytics" },
  { name: "Project Evaluator", icon: Star, desc: "Scores capstone projects on a 5-dimension rubric", category: "analytics" },
  { name: "Progress Report", icon: LineChart, desc: "Generates weekly narrative progress summaries", category: "analytics" },
  // Career (purple)
  { name: "Mock Interviewer", icon: Briefcase, desc: "FAANG-style AI engineering system design interviews", category: "career" },
  { name: "Portfolio Builder", icon: BookOpen, desc: "Turns your projects into structured portfolio entries", category: "career" },
  { name: "Job Match", icon: Search, desc: "Ranks job listings by overlap with your skills", category: "career" },
  // Engagement (purple)
  { name: "Disrupt Prevention", icon: Zap, desc: "Re-engages you with personalized nudges after inactivity", category: "engagement" },
  { name: "Peer Matching", icon: Users, desc: "Finds study partners with overlapping learning goals", category: "engagement" },
  { name: "Community Celebrator", icon: Trophy, desc: "Celebrates milestones with shareable achievement messages", category: "engagement" },
  { name: "Code Review", icon: Code2, desc: "Structured JSON code review with ruff analysis and score", category: "engagement" },
] as const;

const stats = [
  { value: "20", label: "AI Agents", sub: "Specialized coaches" },
  { value: "18+", label: "Lessons", sub: "Hands-on projects" },
  { value: "4.9★", label: "Average rating", sub: "From verified students" },
] as const;

const steps = [
  {
    number: "01",
    title: "You learn",
    desc: "Work through structured lessons and exercises built from real production systems. Watch, code, and submit.",
  },
  {
    number: "02",
    title: "Agents adapt",
    desc: "20 specialized AI agents track your progress, fill knowledge gaps, and continuously personalize your path.",
  },
  {
    number: "03",
    title: "You ship",
    desc: "Graduate with production-ready skills, a portfolio of real projects, and interview-ready confidence.",
  },
] as const;

const tiers: Array<{
  name: string; price: string; highlight: boolean; badge?: string;
  features: string[]; cta: string; href: string;
}> = [
  {
    name: "Free",
    price: "Always free",
    highlight: false,
    features: ["3 AI agents", "5 lessons", "Community access", "Basic progress tracking"],
    cta: "Start free",
    href: "/register",
  },
  {
    name: "Pro",
    price: "$29/mo",
    highlight: true,
    badge: "Most popular",
    features: ["All 20 AI agents", "All 18+ lessons", "1-on-1 AI coaching", "Portfolio builder", "Mock interviews", "Priority support"],
    cta: "Start Pro trial",
    href: "/register?plan=pro",
  },
  {
    name: "Team",
    price: "$99/mo",
    highlight: false,
    features: ["Everything in Pro", "Up to 10 seats", "Team analytics dashboard", "Dedicated support", "Custom curriculum"],
    cta: "Contact sales",
    href: "/contact",
  },
] as const;

const testimonials = [
  {
    quote: "The Socratic Tutor agent genuinely changed how I understand RAG pipelines. It never just gives me the answer — it walks me through the reasoning until I own it.",
    name: "Priya Sundaram",
    title: "Senior ML Engineer",
    company: "Cohere",
    stars: 5,
  },
  {
    quote: "I went from 'I know Python' to deploying a full LangGraph agent system in 6 weeks. The adaptive path meant I never wasted time on things I already knew.",
    name: "Marcus Chen",
    title: "Staff Engineer",
    company: "Stripe",
    stars: 5,
  },
  {
    quote: "The mock interview agent is scary good. Three weeks of sessions with it and I crushed my FAANG AI engineering loops. Worth it for that alone.",
    name: "Aiko Tanaka",
    title: "AI Platform Engineer",
    company: "Google DeepMind",
    stars: 5,
  },
] as const;

const faqs = [
  {
    q: "What makes this different from Coursera or Udemy?",
    a: "We are not a video platform. Every lesson is paired with 20 AI agents that actively monitor your progress, answer questions in context, review your code, schedule your reviews, and personalize your path. No other platform gives you a dedicated AI coach for every dimension of learning.",
  },
  {
    q: "Do I need prior AI or ML experience?",
    a: "You need solid Python and some software engineering experience. You do not need ML theory or prior GenAI experience. The Adaptive Path agent will assess your starting point and calibrate the curriculum to your level.",
  },
  {
    q: "What is included in the free tier?",
    a: "Free gives you access to 3 AI agents (Student Buddy, Coding Assistant, Adaptive Quiz), 5 core lessons, and community access. It is a real learning experience — not a truncated demo.",
  },
  {
    q: "Can I cancel my Pro subscription anytime?",
    a: "Yes. Cancel any time from your account settings. You keep access until the end of your billing period. We also offer a 30-day money-back guarantee, no questions asked.",
  },
  {
    q: "Do you offer team or company licenses?",
    a: "Yes. The Team tier supports up to 10 seats with a shared analytics dashboard. For larger teams or custom curriculum needs, contact us at team@paeplatform.com.",
  },
] as const;

// ---------------------------------------------------------------------------
// Agent card color by category
// ---------------------------------------------------------------------------

function agentCardClass(category: string): string {
  if (category === "creation" || category === "learning") {
    return "border-primary/20 bg-primary/5 hover:border-primary/40";
  }
  if (category === "career" || category === "engagement") {
    return "border-[#7C3AED]/20 bg-[#7C3AED]/5 hover:border-[#7C3AED]/40";
  }
  return "border-border bg-muted/30 hover:border-border/80";
}

function agentIconClass(category: string): string {
  if (category === "creation" || category === "learning") return "text-primary";
  if (category === "career" || category === "engagement") return "text-[#7C3AED]";
  return "text-muted-foreground";
}

// ---------------------------------------------------------------------------
// Page (Server Component)
// ---------------------------------------------------------------------------

export default function LandingPage() {
  return (
    <div className="overflow-x-hidden">
      {/* ------------------------------------------------------------------ */}
      {/* 1. Hero                                                              */}
      {/* ------------------------------------------------------------------ */}
      <SectionHero
        badge="20 AI Agents · LangGraph · Claude API"
        title={
          <>
            Master Production
            <br />
            <span className="text-primary">AI Engineering.</span>
          </>
        }
        subtitle="The only platform where 20 specialized AI agents coach you through real production systems — from LangGraph to enterprise deployment."
        actions={
          <>
            <Link
              href="/register"
              className="inline-flex items-center gap-2 h-11 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
            >
              Start Free <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            <a
              href="#demo-section"
              className="inline-flex items-center gap-2 h-11 rounded-lg border border-border px-6 text-sm font-semibold hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
            >
              Try a live demo
            </a>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          Join 2,400+ engineers building production AI
        </p>
      </SectionHero>

      {/* ------------------------------------------------------------------ */}
      {/* 2. Stats bar                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section
        aria-label="Platform statistics"
        className="max-w-4xl mx-auto px-4 -mt-8 mb-24"
      >
        <MotionFade delay={0.25}>
          <div className="rounded-2xl border border-border bg-card shadow-sm grid grid-cols-3 divide-x divide-border">
            {stats.map(({ value, label, sub }) => (
              <div key={label} className="flex flex-col items-center py-6 px-4 text-center">
                <span className="text-3xl font-bold text-foreground tracking-tight">{value}</span>
                <span className="text-sm font-semibold text-foreground mt-1">{label}</span>
                <span className="text-xs text-muted-foreground mt-0.5">{sub}</span>
              </div>
            ))}
          </div>
        </MotionFade>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 3. Live Demo Widget                                                  */}
      {/* ------------------------------------------------------------------ */}
      <section
        id="demo-section"
        aria-label="Live agent demo"
        className="max-w-3xl mx-auto px-4 mb-24"
      >
        <MotionFade>
          <div className="text-center mb-8">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary mb-3">
              Live preview · Free to try
            </span>
            <h2 className="text-2xl font-bold">See an agent in action</h2>
          </div>
        </MotionFade>
        <MotionFade delay={0.1}>
          <DemoWidget />
        </MotionFade>
        <MotionFade delay={0.2}>
          <div className="text-center mt-6">
            <Link
              href="/register"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:text-primary/80 transition-colors"
            >
              Try it yourself <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        </MotionFade>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 4. Agent Grid                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section aria-label="All 20 AI agents" className="max-w-6xl mx-auto px-4 mb-24">
        <MotionFade>
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-3">20 agents, one platform</h2>
            <p className="text-muted-foreground max-w-xl mx-auto">
              Every aspect of your learning journey has a dedicated AI coach — from content
              ingestion to career support.
            </p>
          </div>
        </MotionFade>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {agents.map(({ name, icon: Icon, desc, category }, i) => (
            <MotionFade key={name} delay={i * 0.03}>
              <div
                className={cn(
                  "rounded-xl border p-4 transition-colors",
                  agentCardClass(category),
                )}
              >
                <Icon
                  className={cn("h-5 w-5 mb-2", agentIconClass(category))}
                  aria-hidden="true"
                />
                <h3 className="text-sm font-semibold text-foreground leading-tight mb-1">
                  {name}
                </h3>
                <p className="text-xs text-muted-foreground leading-relaxed">{desc}</p>
              </div>
            </MotionFade>
          ))}
        </div>

        <MotionFade delay={0.3}>
          <div className="text-center mt-8">
            <Link
              href="/agents"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              Meet all 20 agents <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        </MotionFade>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 5. How It Works                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section
        aria-label="How it works"
        className="relative overflow-hidden py-24 px-4 mb-0"
      >
        <GradientMesh />
        <div className="max-w-4xl mx-auto">
          <MotionFade>
            <div className="text-center mb-14">
              <h2 className="text-3xl font-bold mb-3">How it works</h2>
              <p className="text-muted-foreground">Three steps from zero to production-ready.</p>
            </div>
          </MotionFade>

          <div className="grid md:grid-cols-3 gap-8">
            {steps.map(({ number, title, desc }, i) => (
              <MotionFade key={number} delay={i * 0.1}>
                <div className="relative">
                  <div className="text-5xl font-bold text-primary/20 mb-3 select-none">{number}</div>
                  <h3 className="text-lg font-semibold mb-2">{title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{desc}</p>
                </div>
              </MotionFade>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 6. Pricing Teaser                                                    */}
      {/* ------------------------------------------------------------------ */}
      <section aria-label="Pricing overview" className="max-w-5xl mx-auto px-4 py-24">
        <MotionFade>
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-3">Simple, transparent pricing</h2>
            <p className="text-muted-foreground">Start free. Upgrade when you're ready.</p>
          </div>
        </MotionFade>

        <div className="grid md:grid-cols-3 gap-6">
          {tiers.map(({ name, price, highlight, badge, features, cta, href }, i) => (
            <MotionFade key={name} delay={i * 0.08}>
              <div
                className={cn(
                  "rounded-2xl border p-6 flex flex-col h-full transition-shadow hover:shadow-md",
                  highlight
                    ? "border-primary bg-primary/5 shadow-sm"
                    : "border-border bg-card",
                )}
              >
                <div className="mb-4">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-base font-semibold">{name}</span>
                    {badge && (
                      <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        {badge}
                      </span>
                    )}
                  </div>
                  <div className="text-2xl font-bold">{price}</div>
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
            </MotionFade>
          ))}
        </div>

        <MotionFade delay={0.3}>
          <div className="text-center mt-8">
            <Link
              href="/pricing"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              See full pricing details <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
        </MotionFade>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 7. Testimonials                                                      */}
      {/* ------------------------------------------------------------------ */}
      <section
        aria-label="Student testimonials"
        className="bg-muted/30 py-24 px-4"
      >
        <div className="max-w-5xl mx-auto">
          <MotionFade>
            <div className="text-center mb-12">
              <h2 className="text-3xl font-bold mb-3">What engineers are saying</h2>
            </div>
          </MotionFade>

          <div className="grid md:grid-cols-3 gap-6">
            {testimonials.map(({ quote, name, title, company, stars }, i) => (
              <MotionFade key={name} delay={i * 0.1}>
                <figure className="rounded-xl border border-border bg-card p-6 shadow-sm h-full flex flex-col">
                  <div className="flex gap-0.5 mb-4" aria-label={`${stars} out of 5 stars`}>
                    {Array.from({ length: stars }).map((_, j) => (
                      <Star
                        key={j}
                        className="h-4 w-4 fill-primary text-primary"
                        aria-hidden="true"
                      />
                    ))}
                  </div>
                  <blockquote className="text-sm text-foreground leading-relaxed flex-1 mb-4">
                    &ldquo;{quote}&rdquo;
                  </blockquote>
                  <figcaption>
                    <div className="text-sm font-semibold">{name}</div>
                    <div className="text-xs text-muted-foreground">
                      {title} · {company}
                    </div>
                  </figcaption>
                </figure>
              </MotionFade>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 8. FAQ                                                               */}
      {/* ------------------------------------------------------------------ */}
      <section aria-label="Frequently asked questions" className="max-w-3xl mx-auto px-4 py-24">
        <MotionFade>
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-3">Frequently asked questions</h2>
          </div>
        </MotionFade>

        <MotionFade delay={0.1}>
          <dl className="divide-y divide-border rounded-xl border border-border overflow-hidden">
            {faqs.map(({ q, a }) => (
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
                <dd className="px-6 pb-4 text-sm text-muted-foreground leading-relaxed">
                  {a}
                </dd>
              </details>
            ))}
          </dl>
        </MotionFade>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* 9. Final CTA                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section
        aria-label="Call to action"
        className="relative overflow-hidden py-24 px-4"
      >
        <GradientMesh />
        <MotionFade>
          <div className="max-w-2xl mx-auto text-center">
            <h2 className="text-3xl font-bold mb-4">
              Ready to build production AI systems?
            </h2>
            <p className="text-muted-foreground mb-8">
              Join 2,400+ engineers who are shipping real GenAI products — not just following
              tutorials.
            </p>
            <Link
              href="/register"
              className="inline-flex items-center gap-2 h-12 rounded-lg bg-primary px-8 text-base font-semibold text-primary-foreground hover:bg-primary/90 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
            >
              Start for free <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
            <p className="mt-4 text-xs text-muted-foreground">
              No credit card required. 30-day money-back guarantee on Pro.
            </p>
          </div>
        </MotionFade>
      </section>
    </div>
  );
}
