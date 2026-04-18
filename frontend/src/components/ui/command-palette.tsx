"use client";

import * as React from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { ArrowRight, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { Kbd } from "@/components/ui/kbd";

/**
 * Command palette — Raycast-style ⌘K launcher.
 *
 * Items are grouped, keyboard-navigable, and fuzzy-filtered. Each item has an
 * onSelect that closes the palette after running (unless the handler returns
 * `false` or calls `event.preventDefault()`).
 *
 * Open state is managed by the caller — typical usage:
 *
 *   const [open, setOpen] = useState(false)
 *   useShortcut("mod+k", () => setOpen(true))
 *   <CommandPalette open={open} onOpenChange={setOpen} items={items} />
 */

export interface CommandItem {
  id: string;
  label: string;
  /** Optional smaller secondary text. */
  hint?: string;
  /** Keywords added to the search index. */
  keywords?: string[];
  icon?: React.ReactNode;
  /** Shortcut chip displayed on the right. */
  shortcut?: string;
  group?: string;
  disabled?: boolean;
  onSelect: () => void;
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: CommandItem[];
  placeholder?: string;
  emptyText?: string;
  /** If provided, opens automatically when this shortcut fires. Default "mod+k". */
  triggerShortcut?: string | null;
}

export function matches(item: CommandItem, query: string): boolean {
  if (!query) return true;
  const haystack = [item.label, item.hint, item.group, ...(item.keywords ?? [])]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  // Token-and match — every query term must be a substring of the haystack.
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((t) => haystack.includes(t));
}

export function CommandPalette({
  open,
  onOpenChange,
  items,
  placeholder = "Type a command or search…",
  emptyText = "No results",
  triggerShortcut = "mod+k",
}: CommandPaletteProps) {
  const [query, setQuery] = React.useState("");
  const [highlight, setHighlight] = React.useState(0);

  useShortcut(
    triggerShortcut ?? "",
    () => onOpenChange(true),
    { enabled: Boolean(triggerShortcut) },
  );

  // Reset query + highlight each time the palette opens.
  React.useEffect(() => {
    if (open) {
      setQuery("");
      setHighlight(0);
    }
  }, [open]);

  const filtered = React.useMemo(
    () => items.filter((i) => matches(i, query) && !i.disabled),
    [items, query],
  );

  // Re-clamp highlight when filter shrinks.
  React.useEffect(() => {
    if (highlight >= filtered.length) setHighlight(0);
  }, [filtered.length, highlight]);

  const grouped = React.useMemo(() => {
    const groups = new Map<string | undefined, CommandItem[]>();
    for (const it of filtered) {
      const arr = groups.get(it.group) ?? [];
      arr.push(it);
      groups.set(it.group, arr);
    }
    return Array.from(groups.entries());
  }, [filtered]);

  const runSelected = (index: number) => {
    const item = filtered[index];
    if (!item) return;
    item.onSelect();
    onOpenChange(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => (h + 1) % Math.max(filtered.length, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (h - 1 + filtered.length) % Math.max(filtered.length, 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runSelected(highlight);
    } else if (e.key === "Home") {
      e.preventDefault();
      setHighlight(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setHighlight(Math.max(filtered.length - 1, 0));
    }
  };

  let flatIndex = -1;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className={cn(
            "fixed inset-0 isolate z-50 bg-black/20 backdrop-blur-sm",
            "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0",
            "transition-opacity duration-fast",
          )}
        />
        <DialogPrimitive.Popup
          data-slot="command-palette"
          className={cn(
            "fixed left-1/2 top-[12vh] z-50 w-full max-w-xl -translate-x-1/2",
            "rounded-2xl border border-foreground/10 bg-popover text-popover-foreground outline-none",
            "shadow-[var(--elevation-5)]",
            "data-[starting-style]:opacity-0 data-[starting-style]:scale-95 data-[ending-style]:opacity-0 data-[ending-style]:scale-95",
            "transition-[opacity,scale] duration-base ease-out-quad origin-top",
          )}
          onKeyDown={handleKeyDown}
        >
          <DialogPrimitive.Title className="sr-only">
            Command palette
          </DialogPrimitive.Title>
          <div className="flex items-center gap-2 border-b border-foreground/10 px-3">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setHighlight(0);
              }}
              placeholder={placeholder}
              aria-label="Search commands"
              className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <Kbd keys="esc" />
          </div>
          <div className="max-h-[60vh] overflow-auto p-1" role="listbox">
            {filtered.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-muted-foreground">
                {emptyText}
              </p>
            ) : (
              grouped.map(([group, list]) => (
                <div key={group ?? "__none__"} className="py-1">
                  {group ? (
                    <p className="px-3 pt-1 pb-1 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      {group}
                    </p>
                  ) : null}
                  {list.map((item) => {
                    flatIndex += 1;
                    const active = flatIndex === highlight;
                    const myIndex = flatIndex;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="option"
                        aria-selected={active}
                        onMouseEnter={() => setHighlight(myIndex)}
                        onClick={() => runSelected(myIndex)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm outline-none transition-colors duration-fast",
                          active
                            ? "bg-muted text-foreground"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {item.icon ? (
                          <span className="inline-flex h-5 w-5 shrink-0 items-center justify-center text-muted-foreground">
                            {item.icon}
                          </span>
                        ) : (
                          <span className="h-5 w-5 shrink-0" />
                        )}
                        <span className="flex-1 min-w-0 truncate">{item.label}</span>
                        {item.hint ? (
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {item.hint}
                          </span>
                        ) : null}
                        {item.shortcut ? (
                          <Kbd keys={item.shortcut} className="shrink-0" />
                        ) : active ? (
                          <ArrowRight
                            className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                            aria-hidden="true"
                          />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ))
            )}
          </div>
          <div className="flex items-center justify-between border-t border-foreground/10 px-3 py-2 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Kbd keys="up" /> <Kbd keys="down" /> navigate
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Kbd keys="enter" /> select
            </span>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
