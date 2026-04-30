"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, Search, Users } from "lucide-react";
import { useAdminStudents, type AdminStudentSort } from "@/lib/hooks/use-admin";
import { Badge } from "@/components/ui/badge";

// F13 — sortable columns. The three sort axes that actually exist on
// the User row (joined, name, last_seen) round-trip to the backend.
// Lessons / AI Chats are per-row derived counts; we sort those
// client-side off the limit-capped page that's already rendered.
type ClientSortKey = "lessons_completed" | "agent_interactions";
type SortState =
  | { kind: "server"; key: AdminStudentSort }
  | { kind: "client"; key: ClientSortKey; dir: "asc" | "desc" };

function nextServerSort(
  current: SortState,
  base: "joined" | "name" | "last_seen",
): SortState {
  // Toggle direction when re-clicking the same column; otherwise
  // start descending — that's the more useful default for "joined"
  // and "last seen" (recent-first).
  if (current.kind === "server" && current.key.startsWith(base)) {
    const dir = current.key.endsWith("_desc") ? "asc" : "desc";
    return { kind: "server", key: `${base}_${dir}` as AdminStudentSort };
  }
  return { kind: "server", key: `${base}_desc` as AdminStudentSort };
}

function nextClientSort(current: SortState, key: ClientSortKey): SortState {
  if (current.kind === "client" && current.key === key) {
    return { kind: "client", key, dir: current.dir === "desc" ? "asc" : "desc" };
  }
  return { kind: "client", key, dir: "desc" };
}

function SortIndicator({
  active,
  direction,
}: {
  active: boolean;
  direction: "asc" | "desc";
}) {
  if (!active)
    return <ArrowUpDown className="h-3 w-3 opacity-40" aria-hidden="true" />;
  return direction === "desc" ? (
    <ArrowDown className="h-3 w-3" aria-hidden="true" />
  ) : (
    <ArrowUp className="h-3 w-3" aria-hidden="true" />
  );
}

function serverHeaderState(
  sort: SortState,
  base: "joined" | "name" | "last_seen",
) {
  const active =
    sort.kind === "server" && (sort.key as string).startsWith(base);
  const direction: "asc" | "desc" =
    active && (sort.key as string).endsWith("_asc") ? "asc" : "desc";
  return {
    active,
    direction,
    ariaSort: (active
      ? direction === "desc"
        ? "descending"
        : "ascending"
      : "none") as "ascending" | "descending" | "none",
  };
}

function clientHeaderState(sort: SortState, key: ClientSortKey) {
  const active = sort.kind === "client" && sort.key === key;
  const direction: "asc" | "desc" =
    sort.kind === "client" && active ? sort.dir : "desc";
  return {
    active,
    direction,
    ariaSort: (active
      ? direction === "desc"
        ? "descending"
        : "ascending"
      : "none") as "ascending" | "descending" | "none",
  };
}

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 6 }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 animate-pulse rounded bg-muted" />
        </td>
      ))}
    </tr>
  );
}

export default function AdminStudentsPage() {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState<SortState>({ kind: "server", key: "joined_desc" });

  // DISC-56 — debounced server-side search. The old client-side filter kept
  // the whole student catalog in memory and filtered on every keystroke; this
  // sends one query per ~250ms of idle typing and scales to any catalog size.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const serverSort: AdminStudentSort =
    sort.kind === "server" ? sort.key : "joined_desc";
  const { data: students, isLoading } = useAdminStudents(debounced, serverSort);

  // F13 — apply client-side sort on top of the server-sorted page when
  // the user clicks Lessons or AI Chats.
  const sortedStudents = useMemo(() => {
    if (!students || sort.kind !== "client") return students;
    const key = sort.key;
    const dir = sort.dir === "desc" ? -1 : 1;
    return [...students].sort((a, b) => (a[key] - b[key]) * dir);
  }, [students, sort]);

  const serverHeaderProps = (base: "joined" | "name" | "last_seen") => ({
    ...serverHeaderState(sort, base),
    onClick: () => setSort((s) => nextServerSort(s, base)),
  });
  const clientHeaderProps = (key: ClientSortKey) => ({
    ...clientHeaderState(sort, key),
    onClick: () => setSort((s) => nextClientSort(s, key)),
  });

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-8">
        <div>
          <h1 className="text-2xl font-bold">Students</h1>
          <p className="text-muted-foreground mt-1">
            {sortedStudents?.length ?? 0} {debounced ? "matching" : "registered"} students
          </p>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <input
            type="text"
            placeholder="Search by name or email…"
            aria-label="Search students"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 h-9 w-full md:w-64 rounded-lg border border-input bg-background text-sm outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </div>

      {/* DISC-58 — stacked cards on mobile; the 5-column table overflows phones */}
      <div className="md:hidden space-y-2">
        {isLoading
          ? Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />
            ))
          : (sortedStudents ?? []).map((student) => (
              <Link
                key={student.id}
                href={`/admin/students/${student.id}`}
                className="flex items-center justify-between rounded-lg border p-3 hover:bg-muted/30 transition-colors"
              >
                <div className="min-w-0">
                  <p className="font-medium truncate">{student.full_name}</p>
                  <p className="text-xs text-muted-foreground truncate">{student.email}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {student.lessons_completed} lessons · {student.agent_interactions} chats
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge
                    className={
                      student.is_active
                        ? "bg-green-100 text-green-700 hover:bg-green-100"
                        : "bg-muted text-muted-foreground"
                    }
                  >
                    {student.is_active ? "Active" : "Inactive"}
                  </Badge>
                  <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                </div>
              </Link>
            ))}
        {!isLoading && (sortedStudents?.length ?? 0) === 0 && (
          <div className="py-12 text-center text-muted-foreground">
            <Users className="h-8 w-8 mx-auto mb-2 opacity-40" aria-hidden="true" />
            {debounced ? "No students match your search." : "No students yet."}
          </div>
        )}
      </div>

      <div className="hidden md:block rounded-xl border overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 border-b">
            <tr>
              <th
                className="px-4 py-3 text-left font-medium"
                aria-sort={serverHeaderProps("name").ariaSort}
              >
                <button
                  type="button"
                  onClick={serverHeaderProps("name").onClick}
                  className="inline-flex items-center gap-1.5 hover:text-foreground"
                >
                  Student
                  <SortIndicator
                    active={serverHeaderProps("name").active}
                    direction={serverHeaderProps("name").direction}
                  />
                </button>
              </th>
              <th
                className="px-4 py-3 text-left font-medium"
                aria-sort={serverHeaderProps("joined").ariaSort}
              >
                <button
                  type="button"
                  onClick={serverHeaderProps("joined").onClick}
                  className="inline-flex items-center gap-1.5 hover:text-foreground"
                >
                  Joined
                  <SortIndicator
                    active={serverHeaderProps("joined").active}
                    direction={serverHeaderProps("joined").direction}
                  />
                </button>
              </th>
              <th
                className="px-4 py-3 text-left font-medium"
                aria-sort={clientHeaderProps("lessons_completed").ariaSort}
              >
                <button
                  type="button"
                  onClick={clientHeaderProps("lessons_completed").onClick}
                  className="inline-flex items-center gap-1.5 hover:text-foreground"
                >
                  Lessons
                  <SortIndicator
                    active={clientHeaderProps("lessons_completed").active}
                    direction={clientHeaderProps("lessons_completed").direction}
                  />
                </button>
              </th>
              <th
                className="px-4 py-3 text-left font-medium"
                aria-sort={clientHeaderProps("agent_interactions").ariaSort}
              >
                <button
                  type="button"
                  onClick={clientHeaderProps("agent_interactions").onClick}
                  className="inline-flex items-center gap-1.5 hover:text-foreground"
                >
                  AI Chats
                  <SortIndicator
                    active={clientHeaderProps("agent_interactions").active}
                    direction={clientHeaderProps("agent_interactions").direction}
                  />
                </button>
              </th>
              <th
                className="px-4 py-3 text-left font-medium"
                aria-sort={serverHeaderProps("last_seen").ariaSort}
              >
                <button
                  type="button"
                  onClick={serverHeaderProps("last_seen").onClick}
                  className="inline-flex items-center gap-1.5 hover:text-foreground"
                >
                  Last seen
                  <SortIndicator
                    active={serverHeaderProps("last_seen").active}
                    direction={serverHeaderProps("last_seen").direction}
                  />
                </button>
              </th>
              <th className="px-4 py-3 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)}

            {sortedStudents?.map((student) => (
              <tr
                key={student.id}
                className="hover:bg-muted/30 transition-colors cursor-pointer"
              >
                <td className="px-4 py-3">
                  <Link
                    href={`/admin/students/${student.id}`}
                    className="block hover:underline underline-offset-2"
                  >
                    <p className="font-medium">{student.full_name}</p>
                    <p className="text-xs text-muted-foreground">{student.email}</p>
                  </Link>
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {new Date(student.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 font-medium">{student.lessons_completed}</td>
                <td className="px-4 py-3 font-medium">{student.agent_interactions}</td>
                <td className="px-4 py-3 text-muted-foreground">
                  {student.last_login_at
                    ? new Date(student.last_login_at).toLocaleDateString()
                    : "—"}
                </td>
                <td className="px-4 py-3">
                  <Badge
                    className={
                      student.is_active
                        ? "bg-green-100 text-green-700 hover:bg-green-100"
                        : "bg-muted text-muted-foreground"
                    }
                  >
                    {student.is_active ? "Active" : "Inactive"}
                  </Badge>
                </td>
              </tr>
            ))}

            {!isLoading && (sortedStudents?.length ?? 0) === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-muted-foreground">
                  <Users className="h-8 w-8 mx-auto mb-2 opacity-40" aria-hidden="true" />
                  {debounced ? "No students match your search." : "No students yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
