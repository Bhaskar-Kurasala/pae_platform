import Link from "next/link";
import { ArrowLeft } from "lucide-react";

interface StubPageProps {
  title: string;
  description: string;
}

export function StubPage({ title, description }: StubPageProps) {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className="min-h-[70vh] max-w-2xl mx-auto px-6 py-24 focus:outline-none"
    >
      <Link
        href="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground mb-8"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to home
      </Link>
      <h1 className="text-3xl md:text-4xl font-bold tracking-tight">{title}</h1>
      <p className="mt-4 text-base text-muted-foreground leading-7">{description}</p>
      <p className="mt-6 text-sm text-muted-foreground">
        Full content coming soon. Reach us at{" "}
        <a
          href="mailto:hello@pae.platform"
          className="text-primary hover:underline focus-visible:ring-2 focus-visible:ring-primary/50 rounded"
        >
          hello@pae.platform
        </a>{" "}
        with questions in the meantime.
      </p>
    </main>
  );
}
