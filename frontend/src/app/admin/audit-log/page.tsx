import { cookies } from "next/headers";

interface AuditItem {
  id: string;
  student_id: string | null;
  agent_name: string;
  action_type: string;
  status: string;
  duration_ms: number | null;
  created_at: string;
}

async function getAuditLog(): Promise<AuditItem[]> {
  const cookieStore = await cookies();
  const token = cookieStore.get("access_token")?.value;
  const resp = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/admin/audit-log?limit=100`,
    {
      headers: { Authorization: `Bearer ${token ?? ""}` },
      cache: "no-store",
    },
  );
  if (!resp.ok) return [];
  return resp.json() as Promise<AuditItem[]>;
}

function StatusBadge({ status }: { status: string }) {
  const colour =
    status === "completed"
      ? "bg-green-100 text-green-700"
      : status === "error"
        ? "bg-red-100 text-red-700"
        : "bg-muted text-muted-foreground";
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colour}`}>
      {status}
    </span>
  );
}

export default async function AuditLogPage() {
  const items = await getAuditLog();

  return (
    <div className="p-6 md:p-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">Audit Log</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Recent agent actions — last 100 entries
        </p>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No agent actions recorded yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm" aria-label="Agent action audit log">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-muted-foreground">
                  Agent
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-muted-foreground">
                  Action
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase text-muted-foreground">
                  Status
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground">
                  Duration
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase text-muted-foreground">
                  Time
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-muted/20 transition-colors">
                  <td className="px-4 py-3 font-mono text-xs">{item.agent_name}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{item.action_type}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                    {item.duration_ms != null ? `${item.duration_ms}ms` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                    {new Date(item.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
