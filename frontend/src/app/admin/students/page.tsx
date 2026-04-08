"use client";

import { useState } from "react";
import { Search, Users } from "lucide-react";
import { useAdminStudents } from "@/lib/hooks/use-admin";
import { Badge } from "@/components/ui/badge";

function Skeleton() {
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
  const { data: students, isLoading } = useAdminStudents();
  const [search, setSearch] = useState("");

  const filtered = students?.filter(
    (s) =>
      s.full_name.toLowerCase().includes(search.toLowerCase()) ||
      s.email.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold">Students</h1>
          <p className="text-muted-foreground mt-1">
            {students?.length ?? 0} registered students
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
            className="pl-9 h-9 w-64 rounded-lg border border-input bg-background text-sm outline-none focus:ring-2 focus:ring-primary/50"
          />
        </div>
      </div>

      <div className="rounded-xl border overflow-hidden">
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
              Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} />)}

            {filtered?.map((student) => (
              <tr key={student.id} className="hover:bg-muted/30 transition-colors">
                <td className="px-4 py-3">
                  <p className="font-medium">{student.full_name}</p>
                  <p className="text-xs text-muted-foreground">{student.email}</p>
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

            {!isLoading && filtered?.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                  <Users className="h-8 w-8 mx-auto mb-2 opacity-40" aria-hidden="true" />
                  {search ? "No students match your search." : "No students yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
