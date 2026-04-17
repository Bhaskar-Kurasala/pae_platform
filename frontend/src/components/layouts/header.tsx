"use client";

import { useState } from "react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { AnimatePresence, motion } from "framer-motion";
import { Menu, Moon, Sun, X } from "lucide-react";
import { cn } from "@/lib/utils";

const navLinks = [
  { href: "/courses", label: "Courses" },
  { href: "/agents", label: "Agents" },
  { href: "/pricing", label: "Pricing" },
] as const;

/** Dark/light mode toggle button. */
function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
    >
      {isDark ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}

/** Full-screen mobile nav drawer. */
function MobileDrawer({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-40 bg-black/50 md:hidden"
            aria-hidden="true"
            onClick={onClose}
          />

          {/* Drawer panel */}
          <motion.nav
            key="drawer"
            role="navigation"
            aria-label="Mobile navigation"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ duration: 0.25, ease: [0.25, 0.46, 0.45, 0.94] }}
            className="fixed right-0 top-0 bottom-0 z-50 w-72 bg-background border-l border-border shadow-xl flex flex-col md:hidden"
          >
            {/* Drawer header */}
            <div className="flex items-center justify-between h-16 px-5 border-b border-border">
              <Link
                href="/"
                onClick={onClose}
                className="font-bold text-lg focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded"
              >
                <span className="text-primary">PAE</span>
                <span className="text-foreground"> Platform</span>
              </Link>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close navigation menu"
                className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            {/* Drawer links */}
            <ul className="flex flex-col p-4 gap-1 flex-1" role="list">
              {navLinks.map(({ href, label }) => (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onClose}
                    className="flex items-center rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>

            {/* Drawer CTA */}
            <div className="p-4 border-t border-border flex flex-col gap-2">
              <Link
                href="/login"
                onClick={onClose}
                className="flex items-center justify-center h-10 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                Login
              </Link>
              <Link
                href="/register"
                onClick={onClose}
                className="flex items-center justify-center h-10 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              >
                Start Free →
              </Link>
            </div>
          </motion.nav>
        </>
      )}
    </AnimatePresence>
  );
}

/**
 * Site-wide sticky header for public (marketing) pages.
 *
 * Features:
 * - Sticky with backdrop blur
 * - Logo → /
 * - Desktop nav: Courses, Agents, Pricing
 * - Right side: ThemeToggle, Login, "Start Free →" CTA
 * - Mobile: hamburger → animated slide-in drawer
 * - Fully accessible: role="banner", aria-label, focus rings
 */
export function Header() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      <header
        role="banner"
        className={cn(
          "sticky top-0 z-30 w-full",
          "backdrop-blur-sm bg-background/80 border-b border-border",
          "supports-[backdrop-filter]:bg-background/60",
        )}
      >
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
          {/* Logo */}
          <Link
            href="/"
            aria-label="PAE Platform home"
            className="font-bold text-xl shrink-0 focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded"
          >
            <span className="text-primary">PAE</span>
            <span className="text-foreground"> Platform</span>
          </Link>

          {/* Desktop nav */}
          <nav
            aria-label="Main navigation"
            className="hidden md:flex items-center gap-6"
          >
            {navLinks.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none rounded px-1"
              >
                {label}
              </Link>
            ))}
          </nav>

          {/* Right side actions */}
          <div className="flex items-center gap-2">
            <ThemeToggle />

            {/* Desktop-only auth links */}
            <Link
              href="/login"
              className="hidden md:inline-flex h-9 items-center justify-center rounded-lg px-4 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
            >
              Login
            </Link>
            <Link
              href="/register"
              className="hidden md:inline-flex h-9 items-center justify-center rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
              aria-label="Start for free"
            >
              Start Free →
            </Link>

            {/* Mobile hamburger */}
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation menu"
              aria-expanded={mobileOpen}
              aria-controls="mobile-nav"
              className="md:hidden rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:outline-none"
            >
              <Menu className="h-5 w-5" aria-hidden="true" />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile drawer rendered outside header so it can overlay everything */}
      <MobileDrawer isOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
    </>
  );
}
