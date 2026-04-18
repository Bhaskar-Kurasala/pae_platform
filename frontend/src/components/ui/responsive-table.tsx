"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface ResponsiveColumn<T> {
  key: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  /** Hidden on mobile card layout. */
  hiddenMobile?: boolean;
  /** Primary label on mobile card (first in the stack). Usually one column. */
  primary?: boolean;
  className?: string;
}

export interface ResponsiveTableProps<T> {
  columns: ResponsiveColumn<T>[];
  data: T[];
  rowKey: (row: T) => string;
  caption?: string;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  className?: string;
}

export function ResponsiveTable<T>({
  columns,
  data,
  rowKey,
  caption,
  emptyMessage = "No data.",
  onRowClick,
  className,
}: ResponsiveTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="rounded-xl border border-foreground/10 bg-card p-6 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className={cn("w-full", className)}>
      {/* Desktop / tablet table */}
      <div className="hidden md:block overflow-x-auto rounded-xl border border-foreground/10 bg-card">
        <table className="w-full text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead className="bg-muted/40">
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  className={cn(
                    "px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground",
                    c.className,
                  )}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-foreground/5">
            {data.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  onRowClick && "cursor-pointer hover:bg-muted/40 transition-colors",
                )}
              >
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-4 py-3", c.className)}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile stacked cards */}
      <ul className="md:hidden space-y-2">
        {data.map((row) => {
          const primary = columns.find((c) => c.primary);
          const rest = columns.filter((c) => !c.primary && !c.hiddenMobile);
          return (
            <li key={rowKey(row)}>
              <div
                role={onRowClick ? "button" : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                className={cn(
                  "rounded-xl border border-foreground/10 bg-card p-4 space-y-2",
                  onRowClick && "hover:border-foreground/20 cursor-pointer transition-colors",
                )}
              >
                {primary && (
                  <div className="text-sm font-semibold text-foreground">
                    {primary.cell(row)}
                  </div>
                )}
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
                  {rest.map((c) => (
                    <React.Fragment key={c.key}>
                      <dt className="text-muted-foreground">{c.header}</dt>
                      <dd className="text-foreground text-right">{c.cell(row)}</dd>
                    </React.Fragment>
                  ))}
                </dl>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
