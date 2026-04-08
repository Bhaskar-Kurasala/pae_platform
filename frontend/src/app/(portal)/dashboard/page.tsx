export default function DashboardPage() {
  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold">Dashboard</h1>
      <p className="mt-2 text-muted-foreground">
        Welcome back. Your learning journey continues here.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border bg-card p-6">
          <h2 className="text-sm font-medium text-muted-foreground">Courses Enrolled</h2>
          <p className="mt-2 text-4xl font-bold">0</p>
        </div>
        <div className="rounded-lg border bg-card p-6">
          <h2 className="text-sm font-medium text-muted-foreground">Lessons Completed</h2>
          <p className="mt-2 text-4xl font-bold">0</p>
        </div>
        <div className="rounded-lg border bg-card p-6">
          <h2 className="text-sm font-medium text-muted-foreground">Exercises Submitted</h2>
          <p className="mt-2 text-4xl font-bold">0</p>
        </div>
      </div>
    </div>
  );
}
