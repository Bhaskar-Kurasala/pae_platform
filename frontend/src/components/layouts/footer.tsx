import Link from "next/link";
import { cn } from "@/lib/utils";

const platformLinks = [
  { href: "/courses", label: "Courses" },
  { href: "/agents", label: "Agents" },
  { href: "/pricing", label: "Pricing" },
  { href: "/blog", label: "Blog" },
] as const;

const companyLinks = [
  { href: "/about", label: "About" },
  { href: "/docs", label: "Docs" },
  { href: "/status", label: "Status" },
  { href: "/changelog", label: "Changelog" },
] as const;

const legalLinks = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/security", label: "Security" },
] as const;

const socialLinks = [
  { href: "https://github.com", label: "GitHub", symbol: "GH" },
  { href: "https://twitter.com", label: "X (Twitter)", symbol: "𝕏" },
  { href: "https://linkedin.com", label: "LinkedIn", symbol: "in" },
] as const;

interface FooterColumnProps {
  heading: string;
  children: React.ReactNode;
}

function FooterColumn({ heading, children }: FooterColumnProps) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-foreground mb-3">{heading}</h3>
      {children}
    </div>
  );
}

function FooterLinkList({
  links,
}: {
  links: ReadonlyArray<{ href: string; label: string }>;
}) {
  return (
    <ul className="space-y-2" role="list">
      {links.map(({ href, label }) => (
        <li key={href}>
          <Link
            href={href}
            className="text-sm text-muted-foreground hover:text-foreground transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded"
          >
            {label}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * Site-wide footer for public (marketing) pages.
 *
 * 4-column grid on desktop, 2-col on tablet, 1-col on mobile.
 * Columns: Platform branding, Learn, Company, Legal.
 * Bottom bar: copyright + "Built with Claude API" badge.
 * Teal gradient accent line at the top of the footer.
 */
export function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer
      role="contentinfo"
      className={cn("relative border-t border-border bg-background")}
    >
      {/* Teal gradient accent line */}
      <div
        aria-hidden="true"
        className="absolute top-0 left-0 right-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, oklch(0.63 0.13 164) 30%, oklch(0.52 0.25 283) 70%, transparent 100%)",
        }}
      />

      <div className="max-w-6xl mx-auto px-4 py-12">
        {/* 4-column grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
          {/* Column 1: Branding */}
          <div className="sm:col-span-2 lg:col-span-1">
            <Link
              href="/"
              aria-label="PAE Platform home"
              className="inline-block font-bold text-lg mb-3 focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded"
            >
              <span className="text-primary">PAE</span>
              <span className="text-foreground"> Platform</span>
            </Link>
            <p className="text-sm text-muted-foreground leading-6 max-w-xs mb-4">
              Master production GenAI engineering with 20 AI agents guiding
              your learning journey from zero to deployed.
            </p>

            {/* Social icons */}
            <div className="flex items-center gap-3">
              {socialLinks.map(({ href, label, symbol }) => (
                <a
                  key={href}
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={label}
                  className="rounded-lg h-8 w-8 flex items-center justify-center text-xs font-bold text-muted-foreground hover:text-foreground hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
                >
                  {symbol}
                </a>
              ))}
            </div>
          </div>

          {/* Column 2: Learn */}
          <FooterColumn heading="Learn">
            <FooterLinkList links={platformLinks} />
          </FooterColumn>

          {/* Column 3: Company */}
          <FooterColumn heading="Company">
            <FooterLinkList links={companyLinks} />
          </FooterColumn>

          {/* Column 4: Legal */}
          <FooterColumn heading="Legal">
            <FooterLinkList links={legalLinks} />
          </FooterColumn>
        </div>

        {/* Bottom bar */}
        <div className="mt-12 pt-6 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            &copy; {year} Production AI Engineering Platform. All rights
            reserved.
          </p>

          {/* "Built with Claude API" badge */}
          <div className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted px-3 py-1">
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full bg-primary shrink-0"
            />
            <span className="text-xs font-medium text-muted-foreground">
              Built with{" "}
              <a
                href="https://www.anthropic.com/api"
                target="_blank"
                rel="noopener noreferrer"
                className="text-foreground hover:text-primary transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded"
              >
                Claude API
              </a>
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
