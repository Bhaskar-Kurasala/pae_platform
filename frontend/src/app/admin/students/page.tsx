"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Search, Users } from "lucide-react";
import { useAdminStudents } from "@/lib/hooks/use-admin";
import { Badge } from "@/components/ui/badge";

function SkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 5 }).map((_, i) => (
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

  // DISC-56 — debounced server-side search. The old client-side filter kept
  // the whole student catalog in memory and filtered on every keystroke; this
  // sends one query per ~250ms of idle typing and scales to any catalog size.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  const { data: students, isLoading } = useAdminStudents(debounced);

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-8">
        <div>
          <h1 className="text-2xl font-bold">Students</h1>
          <p className="text-muted-foreground mt-1">
            {students?.length ?? 0} {debounced ? "matching" : "registered"} students
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
          : (students ?? []).map((student) => (
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
        {!isLoading && (students?.length ?? 0) === 0 && (
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
              <th className="px-4 py-3 text-left font-medium">Student</th>
              <th className="px-4 py-3 text-left font-medium">Joined</th>
              <th className="px-4 py-3 text-left font-medium">Lessons</th>
              <th className="px-4 py-3 text-left font-medium">AI Chats</th>
              <th className="px-4 py-3 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)}

            {students?.map((student) => (
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

            {!isLoading && (students?.length ?? 0) === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
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
