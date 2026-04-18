"use client";

import { useEffect, useRef } from "react";

/**
 * Keyboard shortcut system.
 *
 * A shortcut string is mod+key, joined by "+":
 *   - mod:  `mod` (⌘ on macOS, Ctrl elsewhere), `shift`, `alt`, `ctrl`, `meta`
 *   - key:  single letter/digit, or an event.key name (`Escape`, `ArrowUp`, `/`, `?`)
 *
 * Examples:
 *   useShortcut("mod+k", openCommandPalette)
 *   useShortcut("/", focusSearch)
 *   useShortcut(["mod+s", "ctrl+s"], save)
 *   useShortcut("?", openShortcutHelp, { allowInInputs: false })
 *
 * By default, shortcuts fire UNLESS the event originates from an editable
 * element (input, textarea, contenteditable, or a form element with type=text).
 * Pass `allowInInputs: true` to override — rare, used for Escape/Enter.
 */

export type ShortcutHandler = (event: KeyboardEvent) => void;

export interface ShortcutOptions {
  /** Default false. Set true for shortcuts like Escape that should fire inside inputs. */
  allowInInputs?: boolean;
  /** When false, disables the shortcut entirely. Default true. */
  enabled?: boolean;
  /** preventDefault on match. Default true. */
  preventDefault?: boolean;
  /** stopPropagation on match. Default false — only needed for scoped handlers. */
  stopPropagation?: boolean;
  /** Element to attach listener to. Default window. */
  target?: EventTarget | null;
}

function isMac(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform);
}

function isEditable(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
}

function normalizeShortcut(s: string): string {
  return s
    .split("+")
    .map((p) => p.trim().toLowerCase())
    .sort()
    .join("+");
}

function eventMatches(event: KeyboardEvent, shortcut: string): boolean {
  const parts = shortcut.split("+").map((p) => p.trim().toLowerCase());
  const key = parts.find(
    (p) => !["mod", "ctrl", "shift", "alt", "meta"].includes(p),
  );
  if (!key) return false;

  const wantMod = parts.includes("mod");
  const wantCtrl = parts.includes("ctrl");
  const wantShift = parts.includes("shift");
  const wantAlt = parts.includes("alt");
  const wantMeta = parts.includes("meta");

  // `mod` resolves to ⌘ on mac, Ctrl elsewhere.
  const modPressed = isMac() ? event.metaKey : event.ctrlKey;

  if (wantMod && !modPressed) return false;
  if (wantCtrl && !event.ctrlKey) return false;
  if (wantShift !== event.shiftKey) return false;
  if (wantAlt !== event.altKey) return false;
  if (wantMeta && !event.metaKey) return false;

  // When `mod` isn't requested, no unexpected cmd/ctrl should be down.
  if (!wantMod && !wantCtrl && !wantMeta) {
    if (isMac() ? event.metaKey : event.ctrlKey) return false;
  }

  return event.key.toLowerCase() === key;
}

export function useShortcut(
  shortcut: string | string[],
  handler: ShortcutHandler,
  options: ShortcutOptions = {},
): void {
  const {
    allowInInputs = false,
    enabled = true,
    preventDefault = true,
    stopPropagation = false,
    target,
  } = options;

  const handlerRef = useRef(handler);
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);

  const shortcuts = Array.isArray(shortcut) ? shortcut : [shortcut];
  const shortcutKey = shortcuts.join("|");

  useEffect(() => {
    if (!enabled) return;
    const resolvedTarget = target ?? (typeof window !== "undefined" ? window : null);
    if (!resolvedTarget) return;

    const list = shortcutKey.split("|");
    const onKeyDown = (e: Event) => {
      const ke = e as KeyboardEvent;
      if (!allowInInputs && isEditable(ke.target)) return;
      for (const s of list) {
        if (eventMatches(ke, s)) {
          if (preventDefault) ke.preventDefault();
          if (stopPropagation) ke.stopPropagation();
          handlerRef.current(ke);
          return;
        }
      }
    };

    resolvedTarget.addEventListener("keydown", onKeyDown);
    return () => resolvedTarget.removeEventListener("keydown", onKeyDown);
  }, [enabled, allowInInputs, preventDefault, stopPropagation, target, shortcutKey]);
}

// ─── Registry ──────────────────────────────────────────────────
// The registry is a flat catalogue of every app-wide shortcut, used by the
// "?" help overlay and command palette to stay discoverable.

export interface ShortcutRegistryEntry {
  id: string;
  keys: string;
  label: string;
  scope?: "global" | "portal" | "editor" | "chat";
  /** If set, the help UI can group shortcuts. */
  group?: string;
}

const registry = new Map<string, ShortcutRegistryEntry>();
const registryListeners = new Set<() => void>();

export function registerShortcut(entry: ShortcutRegistryEntry): () => void {
  registry.set(entry.id, entry);
  registryListeners.forEach((l) => l());
  return () => {
    registry.delete(entry.id);
    registryListeners.forEach((l) => l());
  };
}

export function listShortcuts(): ShortcutRegistryEntry[] {
  return Array.from(registry.values());
}

export function subscribeToShortcuts(listener: () => void): () => void {
  registryListeners.add(listener);
  return () => {
    registryListeners.delete(listener);
  };
}

/**
 * Combines useShortcut + registry. Use this for app-wide shortcuts so they
 * appear in the help overlay automatically.
 */
export function useRegisteredShortcut(
  entry: ShortcutRegistryEntry,
  handler: ShortcutHandler,
  options: ShortcutOptions = {},
): void {
  useShortcut(entry.keys, handler, options);
  const entryRef = useRef(entry);
  useEffect(() => {
    entryRef.current = entry;
  });
  useEffect(() => registerShortcut(entryRef.current), [entry.id]);
}

// Exported for tests.
export const _internal = { normalizeShortcut, eventMatches, isMac };
