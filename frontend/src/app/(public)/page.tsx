import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 px-4">
      <div className="text-center">
        <h1 className="text-5xl font-bold tracking-tight">
          Production <span className="text-primary">AI Engineering</span> Platform
        </h1>
        <p className="mt-4 max-w-xl text-lg text-muted-foreground">
          Master GenAI engineering with 18+ AI agents guiding your learning journey.
        </p>
      </div>
      <div className="flex gap-4">
        <Link
          href="/dashboard"
          className="inline-flex h-11 items-center justify-center rounded-lg bg-primary px-6 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          Get Started
        </Link>
        <Link
          href="/courses"
          className="inline-flex h-11 items-center justify-center rounded-lg border border-border bg-background px-6 text-sm font-medium transition-colors hover:bg-muted"
        >
          Browse Courses
        </Link>
      </div>
    </main>
  );
}
