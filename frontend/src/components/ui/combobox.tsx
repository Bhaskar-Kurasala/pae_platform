"use client";

import * as React from "react";
import { Combobox as ComboboxPrimitive } from "@base-ui/react/combobox";
import { Check, ChevronDown, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Combobox — searchable select built on Base UI.
 *
 * Two shapes, same component:
 *   - Single: pass items, value is the selected ComboboxItem (or null).
 *   - Multiple: `multiple` prop, value is ComboboxItem[].
 *
 * Items are always `{ value, label }`. If you need icons or descriptions,
 * pass a `renderItem` function.
 */

export interface ComboboxItem {
  value: string;
  label: string;
  /** When true, item is not selectable. */
  disabled?: boolean;
  /** Optional group name — items with the same group are shown under a header. */
  group?: string;
}

interface BaseProps {
  items: ComboboxItem[];
  placeholder?: string;
  emptyText?: string;
  /** Render a custom row for each item. Fallback: label only. */
  renderItem?: (item: ComboboxItem) => React.ReactNode;
  /** Size of the trigger. Default md. */
  size?: "sm" | "md";
  /** Width of the popup. Default "trigger" (match trigger width). */
  popupWidth?: "trigger" | number | "auto";
  disabled?: boolean;
  invalid?: boolean;
  className?: string;
  id?: string;
  /** aria-label for the input. Required when no visible label. */
  "aria-label"?: string;
}

interface SingleProps extends BaseProps {
  multiple?: false;
  value: ComboboxItem | null;
  onValueChange: (value: ComboboxItem | null) => void;
  clearable?: boolean;
}

interface MultiProps extends BaseProps {
  multiple: true;
  value: ComboboxItem[];
  onValueChange: (value: ComboboxItem[]) => void;
  clearable?: boolean;
}

export type ComboboxProps = SingleProps | MultiProps;

function itemsByGroup(items: ComboboxItem[]) {
  const groups = new Map<string | undefined, ComboboxItem[]>();
  for (const item of items) {
    const g = item.group;
    const list = groups.get(g) ?? [];
    list.push(item);
    groups.set(g, list);
  }
  return Array.from(groups.entries());
}

export function Combobox(props: ComboboxProps) {
  const {
    items,
    placeholder = "Select…",
    emptyText = "No results",
    renderItem,
    size = "md",
    popupWidth = "trigger",
    disabled,
    invalid,
    className,
    id,
  } = props;

  const grouped = React.useMemo(() => itemsByGroup(items), [items]);

  const triggerHeight = size === "sm" ? "h-7" : "h-8";
  const popupWidthStyle =
    popupWidth === "trigger"
      ? { width: "var(--anchor-width)" }
      : popupWidth === "auto"
        ? {}
        : { width: popupWidth };

  return (
    <ComboboxPrimitive.Root
      items={items}
      multiple={props.multiple}
      value={(props.multiple ? props.value : props.value) as never}
      onValueChange={((v: ComboboxItem | ComboboxItem[] | null) => {
        if (props.multiple) props.onValueChange((v ?? []) as ComboboxItem[]);
        else props.onValueChange((v ?? null) as ComboboxItem | null);
      }) as never}
      itemToStringLabel={(i: ComboboxItem) => i.label}
      itemToStringValue={(i: ComboboxItem) => i.value}
      disabled={disabled}
    >
      <ComboboxPrimitive.InputGroup
        className={cn(
          "flex items-center gap-1 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none",
          "transition-[border-color,box-shadow] duration-fast ease-out-quad",
          "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
          "data-[invalid=true]:border-destructive data-[invalid=true]:ring-3 data-[invalid=true]:ring-destructive/20",
          "dark:bg-input/30",
          triggerHeight,
          className,
        )}
        data-invalid={invalid || undefined}
      >
        {props.multiple && props.value.length > 0 ? (
          <ComboboxPrimitive.Chips className="flex flex-wrap items-center gap-1 py-1">
            {props.value.map((item) => (
              <ComboboxPrimitive.Chip
                key={item.value}
                className="inline-flex items-center gap-1 rounded-md bg-foreground/[0.06] px-1.5 py-0.5 text-xs"
              >
                {item.label}
                <ComboboxPrimitive.ChipRemove
                  aria-label={`Remove ${item.label}`}
                  className="inline-flex h-3.5 w-3.5 items-center justify-center rounded hover:bg-foreground/10"
                >
                  <X className="h-2.5 w-2.5" />
                </ComboboxPrimitive.ChipRemove>
              </ComboboxPrimitive.Chip>
            ))}
          </ComboboxPrimitive.Chips>
        ) : null}
        <ComboboxPrimitive.Input
          id={id}
          placeholder={
            props.multiple && props.value.length > 0 ? undefined : placeholder
          }
          aria-label={props["aria-label"]}
          className="h-full flex-1 min-w-0 bg-transparent outline-none placeholder:text-muted-foreground"
        />
        {(props.clearable ?? true) ? (
          <ComboboxPrimitive.Clear
            aria-label="Clear selection"
            className="inline-flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-3 w-3" />
          </ComboboxPrimitive.Clear>
        ) : null}
        <ComboboxPrimitive.Trigger
          aria-label="Toggle options"
          className="inline-flex h-5 w-5 items-center justify-center text-muted-foreground"
        >
          <ChevronDown className="h-3.5 w-3.5 transition-transform duration-fast data-[popup-open]:rotate-180" />
        </ComboboxPrimitive.Trigger>
      </ComboboxPrimitive.InputGroup>

      <ComboboxPrimitive.Portal>
        <ComboboxPrimitive.Positioner sideOffset={6} align="start">
          <ComboboxPrimitive.Popup
            style={popupWidthStyle}
            className={cn(
              "z-50 max-h-[var(--available-height)] overflow-auto rounded-xl border border-foreground/10 bg-popover p-1 text-popover-foreground outline-none",
              "shadow-[var(--elevation-3)]",
              "data-[starting-style]:opacity-0 data-[starting-style]:scale-95 data-[ending-style]:opacity-0 data-[ending-style]:scale-95",
              "transition-[opacity,scale] duration-fast ease-out-quad origin-[var(--transform-origin)]",
            )}
          >
            <ComboboxPrimitive.Empty className="px-2 py-3 text-center text-xs text-muted-foreground">
              {emptyText}
            </ComboboxPrimitive.Empty>
            <ComboboxPrimitive.List>
              {grouped.map(([group, list]) => (
                <ComboboxPrimitive.Group key={group ?? "__none__"}>
                  {group ? (
                    <ComboboxPrimitive.GroupLabel className="px-2 pt-1.5 pb-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      {group}
                    </ComboboxPrimitive.GroupLabel>
                  ) : null}
                  {list.map((item) => (
                    <ComboboxPrimitive.Item
                      key={item.value}
                      value={item}
                      disabled={item.disabled}
                      className={cn(
                        "flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none",
                        "data-[highlighted]:bg-muted data-[highlighted]:text-foreground",
                        "data-[selected]:bg-primary/10 data-[selected]:text-primary-foreground dark:data-[selected]:bg-primary/20",
                        "data-disabled:pointer-events-none data-disabled:opacity-50",
                      )}
                    >
                      <ComboboxPrimitive.ItemIndicator className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-primary">
                        <Check className="h-3 w-3" />
                      </ComboboxPrimitive.ItemIndicator>
                      <span className="flex-1 truncate">
                        {renderItem ? renderItem(item) : item.label}
                      </span>
                    </ComboboxPrimitive.Item>
                  ))}
                </ComboboxPrimitive.Group>
              ))}
            </ComboboxPrimitive.List>
          </ComboboxPrimitive.Popup>
        </ComboboxPrimitive.Positioner>
      </ComboboxPrimitive.Portal>
    </ComboboxPrimitive.Root>
  );
}
