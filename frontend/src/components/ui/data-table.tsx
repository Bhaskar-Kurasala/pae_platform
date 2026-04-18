"use client";

import * as React from "react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type ColumnFiltersState,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
  type VisibilityState,
} from "@tanstack/react-table";
import {
  ArrowUpDown,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";

/**
 * DataTable — TanStack v8 table wrapper.
 *
 * What you get out of the box:
 *   - Sorting (click header)
 *   - Global filter (search input)
 *   - Pagination (page size picker + prev/next)
 *   - Row selection (if columns include a select column)
 *   - Loading skeleton + empty state
 *   - Column visibility (opt-in via prop)
 *
 * Style: Linear-grade table — subtle borders, tight rows, muted header,
 * hover highlight, focus-visible outlines. All layout uses semantic <table>.
 */

export interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  /** Show skeleton rows in place of data. */
  loading?: boolean;
  /** Skeleton row count when loading. Default 6. */
  loadingRows?: number;
  /** Enable global search. Default true. */
  searchable?: boolean;
  searchPlaceholder?: string;
  /** Enable pagination controls. Default true. */
  paginated?: boolean;
  /** Page size options. Default [10, 25, 50]. */
  pageSizeOptions?: number[];
  /** Initial page size. Default 10. */
  initialPageSize?: number;
  /** Called with the row-selection map whenever it changes. */
  onRowSelectionChange?: (selection: RowSelectionState) => void;
  /** Called when a row is clicked. Receives the row's original data. */
  onRowClick?: (row: TData) => void;
  /** Extra toolbar nodes rendered on the right of the search input. */
  toolbar?: React.ReactNode;
  /** Empty state overrides. */
  emptyTitle?: string;
  emptyDescription?: string;
  className?: string;
  /** Fixed row height in px. Default 44 ("compact"). */
  rowHeight?: number;
}

export function DataTable<TData, TValue>({
  columns,
  data,
  loading = false,
  loadingRows = 6,
  searchable = true,
  searchPlaceholder = "Search…",
  paginated = true,
  pageSizeOptions = [10, 25, 50],
  initialPageSize = 10,
  onRowSelectionChange,
  onRowClick,
  toolbar,
  emptyTitle = "No results",
  emptyDescription = "Try adjusting your search or filters.",
  className,
  rowHeight = 44,
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [globalFilter, setGlobalFilter] = React.useState("");
  const [pagination, setPagination] = React.useState<PaginationState>({
    pageIndex: 0,
    pageSize: initialPageSize,
  });

  const table = useReactTable({
    data,
    columns,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      globalFilter,
      pagination,
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    onGlobalFilterChange: setGlobalFilter,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: paginated ? getPaginationRowModel() : undefined,
  });

  React.useEffect(() => {
    onRowSelectionChange?.(rowSelection);
  }, [rowSelection, onRowSelectionChange]);

  const visibleRows = table.getRowModel().rows;
  const showEmpty = !loading && visibleRows.length === 0;

  return (
    <div className={cn("w-full space-y-3", className)}>
      {(searchable || toolbar) && (
        <div className="flex items-center justify-between gap-2">
          {searchable ? (
            <Input
              value={globalFilter}
              onChange={(e) => setGlobalFilter(e.target.value)}
              placeholder={searchPlaceholder}
              aria-label="Search table"
              className="h-8 max-w-xs"
            />
          ) : (
            <span />
          )}
          {toolbar ? (
            <div className="flex items-center gap-2">{toolbar}</div>
          ) : null}
        </div>
      )}

      <div className="rounded-xl border border-foreground/10 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead className="bg-muted/40">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-foreground/10">
                  {hg.headers.map((header) => {
                    const canSort = header.column.getCanSort();
                    const sorted = header.column.getIsSorted();
                    return (
                      <th
                        key={header.id}
                        className="h-10 px-3 text-left align-middle text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground"
                        style={{ width: header.getSize() === 150 ? undefined : header.getSize() }}
                      >
                        {header.isPlaceholder ? null : canSort ? (
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className={cn(
                              "inline-flex items-center gap-1.5 rounded-sm outline-none",
                              "hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50",
                              sorted && "text-foreground",
                            )}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" ? (
                              <ChevronUp className="h-3 w-3" aria-hidden="true" />
                            ) : sorted === "desc" ? (
                              <ChevronDown className="h-3 w-3" aria-hidden="true" />
                            ) : (
                              <ArrowUpDown
                                className="h-3 w-3 opacity-40"
                                aria-hidden="true"
                              />
                            )}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: loadingRows }).map((_, i) => (
                  <tr key={`sk-${i}`} className="border-b border-foreground/5 last:border-b-0">
                    {table.getVisibleFlatColumns().map((col) => (
                      <td
                        key={col.id}
                        className="px-3"
                        style={{ height: rowHeight }}
                      >
                        <Skeleton shape="text" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : showEmpty ? (
                <tr>
                  <td colSpan={columns.length} className="p-0">
                    <EmptyState
                      title={emptyTitle}
                      description={emptyDescription}
                      size="compact"
                    />
                  </td>
                </tr>
              ) : (
                visibleRows.map((row) => (
                  <tr
                    key={row.id}
                    data-state={row.getIsSelected() ? "selected" : undefined}
                    onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                    className={cn(
                      "border-b border-foreground/5 last:border-b-0 transition-colors duration-fast",
                      "hover:bg-muted/40 data-[state=selected]:bg-primary/5",
                      onRowClick && "cursor-pointer",
                    )}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td
                        key={cell.id}
                        className="px-3 align-middle"
                        style={{ height: rowHeight }}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {paginated && !loading && data.length > 0 ? (
        <DataTablePagination
          table={table}
          pageSizeOptions={pageSizeOptions}
          totalRows={table.getFilteredRowModel().rows.length}
        />
      ) : null}
    </div>
  );
}

interface PaginationProps<TData> {
  table: ReturnType<typeof useReactTable<TData>>;
  pageSizeOptions: number[];
  totalRows: number;
}

function DataTablePagination<TData>({
  table,
  pageSizeOptions,
  totalRows,
}: PaginationProps<TData>) {
  const { pageIndex, pageSize } = table.getState().pagination;
  const pageCount = table.getPageCount();
  const start = totalRows === 0 ? 0 : pageIndex * pageSize + 1;
  const end = Math.min((pageIndex + 1) * pageSize, totalRows);
  const selected = Object.keys(table.getState().rowSelection).length;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
      <div className="flex items-center gap-3">
        <span>
          {start}–{end} of {totalRows}
        </span>
        {selected > 0 ? (
          <span className="text-foreground">· {selected} selected</span>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <label className="inline-flex items-center gap-2">
          Rows
          <select
            value={pageSize}
            onChange={(e) => table.setPageSize(Number(e.target.value))}
            className="h-7 rounded-md border border-input bg-transparent px-1.5 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring/50 dark:bg-input/30"
            aria-label="Rows per page"
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => table.setPageIndex(0)}
            disabled={!table.getCanPreviousPage()}
            aria-label="First page"
          >
            <ChevronsLeft className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            aria-label="Previous page"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="px-1.5 tabular-nums">
            {pageIndex + 1} / {Math.max(pageCount, 1)}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            aria-label="Next page"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => table.setPageIndex(pageCount - 1)}
            disabled={!table.getCanNextPage()}
            aria-label="Last page"
          >
            <ChevronsRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

export type { ColumnDef, RowSelectionState } from "@tanstack/react-table";
