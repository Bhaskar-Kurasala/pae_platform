"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, Code2, Sun, MessageSquare, LayoutDashboard } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDueCards } from "@/lib/hooks/use-srs";

const ITEMS = [
  { href: "/today", label: "Today", icon: Sun },
  { href: "/courses", label: "Courses", icon: BookOpen },
  { href: "/studio", label: "Studio", icon: Code2 },
  { href: "/dashboard", label: "Stats", icon: LayoutDashboard },
  { href: "/chat", label: "Tutor", icon: MessageSquare },
];

export function MobileBottomNav() {
  const pathname = usePathname();
  const { data: dueCards } = useDueCards(50);
  const dueCount = dueCards?.length ?? 0;

  return (
    <nav
      aria-label="Primary mobile navigation"
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80 pb-[env(safe-area-inset-bottom)]"
    >
      <ul className="flex items-stretch justify-around">
        {ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href} className="flex-1">
              <Link
                href={href}
                aria-label={label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium transition-colors",
                  active
                    ? "text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="relative">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                  {href === "/today" && dueCount > 0 && (
                    <span
                      className="absolute -top-1 -right-1.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-amber-500 px-1 text-[9px] font-bold text-white"
                      aria-label={`${dueCount} due`}
                    >
                      {dueCount > 9 ? "9+" : dueCount}
                    </span>
                  )}
                </span>
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
