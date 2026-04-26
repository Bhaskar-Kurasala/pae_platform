"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import styles from "./console.module.css";

// The admin console is the canonical /admin entry — single production-quality
// surface. The previous KPI dashboard was retired in favour of this v1 design.

// ── Types — mirror AdminConsoleResponse from backend/admin.py ───────────

interface PulseCard {
  metric_key: string;
  label: string;
  value: string;
  unit: string;
  delta: number;
  delta_text: string;
  color: string;
  invert_delta: boolean;
  spark: number[];
}
interface FunnelStage {
  name: string;
  count: number;
}
interface FeatureTile {
  feature_key: string;
  name: string;
  count: string;
  sub: string;
  cold: boolean;
  bars: number[];
}
interface CallItem {
  student_id: string;
  time: string;
  reason: string;
}
interface EventItem {
  student_id: string | null;
  kind: "promo" | "capstone" | "purchase" | "review" | "signup" | string;
  text: string;
  time_label: string;
}
interface Revenue {
  month_total: string;
  new_purchases: string;
  renewals: string;
  refunds: string;
  spark: number[];
}
interface ConsoleStudent {
  id: string;
  name: string;
  email: string | null;
  track: string;
  stage: string;
  progress: number;
  streak: number;
  last_seen: number;
  risk: number;
  paid: boolean;
  joined: string;
  city: string | null;
  sessions14: number;
  flashcards: number;
  agent_q: number;
  reviews: number;
  notes: number;
  labs: number;
  capstones: number;
  purchases: number;
  risk_reason: string | null;
}
interface ConsoleResponse {
  students: ConsoleStudent[];
  pulse: PulseCard[];
  funnel: FunnelStage[];
  features: FeatureTile[];
  calls: CallItem[];
  events: EventItem[];
  revenue: Revenue;
  synced_at: string;
}

// ── Helpers ─────────────────────────────────────────────────────────────

const AVATAR_COLORS: [string, string][] = [
  ["#356d50", "#5fa37f"],
  ["#b8862d", "#e8be72"],
  ["#9a4b3b", "#d96252"],
  ["#4a4a8a", "#7c7cb6"],
  ["#6b8a36", "#9bb966"],
  ["#2d6478", "#5a99af"],
  ["#7a3d6b", "#a86596"],
  ["#8a5a3d", "#b58761"],
];

function avatarBg(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  const c = AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
  return `linear-gradient(135deg, ${c[0]}, ${c[1]})`;
}
function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}
function riskTier(r: number): "severe" | "high" | "med" | "low" {
  if (r >= 75) return "severe";
  if (r >= 50) return "high";
  if (r >= 30) return "med";
  return "low";
}
function riskLabel(r: number): string {
  const t = riskTier(r);
  return t === "severe" ? "Severe" : t === "high" ? "High" : t === "med" ? "Watch" : "Healthy";
}
function lastSeenText(d: number): string {
  if (d === 0) return "Today";
  if (d === 1) return "1d ago";
  return `${d}d ago`;
}
function sparkPath(data: number[], w = 120, h = 24): { line: string; area: string } {
  if (!data.length) return { line: "", area: "" };
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const step = w / Math.max(1, data.length - 1);
  const pts = data.map((v, i) => [i * step, h - ((v - min) / range) * (h - 4) - 2] as const);
  const line =
    "M " + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ");
  const area =
    `M 0,${h} L ` +
    pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ") +
    ` L ${w},${h} Z`;
  return { line, area };
}

type FilterKey = "all" | "severe" | "high" | "paid-stalled" | "thriving" | "new";
type SortKey = "name" | "role" | "stage" | "progress" | "streak" | "last" | "risk";
type SortDir = "asc" | "desc";

const TAG_LABELS: Record<string, string> = {
  promo: "Promo",
  capstone: "Capstone",
  purchase: "Purchase",
  review: "Review",
  signup: "Signup",
};

// ── Page ────────────────────────────────────────────────────────────────

export default function AdminConsoleV1Page() {
  const { user } = useAuthStore();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "risk", dir: "desc" });
  const [search, setSearch] = useState("");
  const [openStudentId, setOpenStudentId] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<ConsoleResponse>({
    queryKey: ["admin", "console", "v1"],
    queryFn: () => api.get<ConsoleResponse>("/api/v1/admin/console/v1"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const students = data?.students ?? [];

  const topRisk = useMemo(
    () => [...students].sort((a, b) => b.risk - a.risk).slice(0, 3),
    [students],
  );

  const filtered = useMemo(() => {
    let list = [...students];
    if (filter === "severe") list = list.filter((s) => s.risk >= 75);
    else if (filter === "high") list = list.filter((s) => s.risk >= 50 && s.risk < 75);
    else if (filter === "paid-stalled") list = list.filter((s) => s.paid && s.last_seen >= 5);
    else if (filter === "thriving") list = list.filter((s) => s.risk < 30);
    else if (filter === "new") {
      const newJoiners = ["Apr 19", "Apr 21", "Apr 22"];
      list = list.filter((s) => newJoiners.includes(s.joined));
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter((s) => s.name.toLowerCase().includes(q));
    }
    const k = sort.key;
    const dir = sort.dir === "asc" ? 1 : -1;
    list.sort((a, b) => {
      if (k === "name") return a.name.localeCompare(b.name) * dir;
      if (k === "role") return a.track.localeCompare(b.track) * dir;
      if (k === "stage") return a.stage.localeCompare(b.stage) * dir;
      if (k === "last") return (a.last_seen - b.last_seen) * dir;
      if (k === "progress") return (a.progress - b.progress) * dir;
      if (k === "streak") return (a.streak - b.streak) * dir;
      return (a.risk - b.risk) * dir;
    });
    return list;
  }, [students, filter, search, sort]);

  const openStudent = openStudentId
    ? students.find((s) => s.id === openStudentId) ?? null
    : null;

  const onSortClick = (k: SortKey) => {
    setSort((cur) => {
      if (cur.key === k) {
        return { key: k, dir: cur.dir === "asc" ? "desc" : "asc" };
      }
      return { key: k, dir: k === "name" || k === "role" || k === "stage" ? "asc" : "desc" };
    });
  };

  const adminInitials = initials(user?.full_name ?? "Admin");

  return (
    <div className={styles.root} data-theme={theme}>
      {/* TOP BAR */}
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <b>
            Career<i>Forge</i>
          </b>
          <span className={styles.consoleTag}>Admin</span>
        </div>
        <div className={styles.tbDivider} />
        <div className={styles.tbSearch}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
          <input
            type="search"
            aria-label="Search"
            placeholder="Search students, capstones, or events…"
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className={styles.tbSpacer} />
        <div className={styles.livePulse}>
          <span className={styles.liveDot} />
          LIVE · {data ? `synced ${new Date(data.synced_at).toLocaleTimeString()}` : "syncing…"}
        </div>
        <div className={styles.adminId}>
          <div className={styles.adminAvatar}>{adminInitials}</div>
          <div className={styles.adminName}>
            <b>{user?.full_name ?? "Admin"}</b>
            <span>{user?.role === "admin" ? "Founder · Admin" : "Member"}</span>
          </div>
        </div>
        <button
          className={styles.themeToggle}
          aria-label="Toggle theme"
          onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
        >
          <span className={`${styles.themeOpt} ${theme === "light" ? styles.active : ""}`}>
            <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <circle cx="7" cy="7" r="2.4" />
              <path d="M7 1v1.4M7 11.6V13M1 7h1.4M11.6 7H13M2.6 2.6l1 1M10.4 10.4l1 1M2.6 11.4l1-1M10.4 3.6l1-1" />
            </svg>
          </span>
          <span className={`${styles.themeOpt} ${theme === "dark" ? styles.active : ""}`}>
            <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11.5 8.5A4.5 4.5 0 015.5 2.5a5 5 0 106 6z" />
            </svg>
          </span>
        </button>
      </header>

      {isLoading ? (
        <div className={styles.skeleton}>Loading admin console…</div>
      ) : isError ? (
        <div className={styles.skeleton}>Failed to load admin console data.</div>
      ) : !data ? null : (
        <div className={styles.layout}>
          <main>
            {/* ACTION BAND */}
            <section className={styles.actionBand}>
              <div className={styles.abTop}>
                <div className={styles.abTopLeft}>
                  <div className={styles.abEyebrow}>
                    <span className={styles.abDot} />
                    This week&apos;s call list
                  </div>
                  <h2 className={styles.abTitle}>
                    <b>{topRisk.length} students</b> need a personal nudge.
                  </h2>
                  <p className={styles.abSub}>
                    These are the learners whose momentum has slipped most against their own
                    baseline. A 15-minute call usually pulls them back into the cohort.
                  </p>
                </div>
                <button
                  className={styles.abBtn}
                  onClick={() => {
                    setFilter("severe");
                    document
                      .getElementById("studentSection")
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                >
                  See full call list
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </button>
              </div>
              <div className={styles.abCards}>
                {topRisk.map((s) => (
                  <div
                    key={s.id}
                    className={`${styles.riskCard} ${styles.severe}`}
                    onClick={() => setOpenStudentId(s.id)}
                  >
                    <div className={styles.rcHead}>
                      <div className={styles.rcAvatar} style={{ background: avatarBg(s.id) }}>
                        {initials(s.name)}
                      </div>
                      <div>
                        <div className={styles.rcName}>{s.name}</div>
                        <div className={styles.rcRole}>
                          {s.track} · {s.stage}
                        </div>
                      </div>
                      <div className={styles.rcScore}>{s.risk}</div>
                    </div>
                    <div className={styles.rcReason}>
                      {s.risk_reason ??
                        `${s.last_seen}d silent · streak broken · stuck at ${s.progress}%`}
                    </div>
                    <div className={styles.rcMeta}>
                      {s.paid && <span className={`${styles.rcTag} ${styles.paid}`}>Paid</span>}
                      <span className={`${styles.rcTag} ${styles.danger}`}>{s.last_seen}d silent</span>
                      <span className={`${styles.rcTag} ${styles.warn}`}>Streak: {s.streak}</span>
                    </div>
                    <div className={styles.rcCta}>
                      <button
                        className={`${styles.rcBtn} ${styles.primary}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpenStudentId(s.id);
                        }}
                      >
                        Open profile
                      </button>
                      <button
                        className={`${styles.rcBtn} ${styles.ghost}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        Schedule call
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            {/* PULSE STRIP */}
            <section className={styles.section}>
              <div className={styles.sectionHead}>
                <div>
                  <div className={styles.sectionEyebrow}>Platform pulse · last 24 hours</div>
                  <div className={styles.sectionTitle}>How we&apos;re doing right now</div>
                </div>
                <div className={styles.sectionActions}>
                  <button className={`${styles.tabPill} ${styles.on}`}>24h</button>
                  <button className={styles.tabPill}>7d</button>
                  <button className={styles.tabPill}>30d</button>
                </div>
              </div>
              <div className={styles.pulseStrip}>
                {data.pulse.map((p) => {
                  const { line, area } = sparkPath(p.spark);
                  const up = p.delta >= 0;
                  const cls = p.invert_delta ? (p.delta < 0 ? "up" : "down") : up ? "up" : "down";
                  return (
                    <div key={p.metric_key} className={styles.pulseCard}>
                      <div className={styles.pcLabel}>{p.label}</div>
                      <div className={styles.pcValue}>
                        {p.value}
                        <span className="unit">{p.unit}</span>
                      </div>
                      <div className={`${styles.pcDelta} ${cls === "up" ? styles.up : styles.down}`}>
                        <span className={styles.pcDeltaArrow}>{up ? "▲" : "▼"}</span>
                        <span>
                          {Math.abs(p.delta)}% · {p.delta_text}
                        </span>
                      </div>
                      <svg className={styles.pcSpark} viewBox="0 0 120 24" preserveAspectRatio="none">
                        <path className="area" d={area} fill={p.color} opacity="0.12" />
                        <path className="line" d={line} stroke={p.color} fill="none" />
                      </svg>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* FUNNEL */}
            <section className={styles.section}>
              <div className={styles.sectionHead}>
                <div>
                  <div className={styles.sectionEyebrow}>Learner funnel</div>
                  <div className={styles.sectionTitle}>
                    Where students are right now — and where they leak.
                  </div>
                  <div className={styles.sectionSub}>
                    From signup to hire. The bigger the drop between two stages, the more
                    attention that transition needs.
                  </div>
                </div>
              </div>
              <div className={styles.funnelCard}>
                <FunnelChart stages={data.funnel} />
                <div className={styles.funnelStages}>
                  {data.funnel.map((d, i) => {
                    const next = data.funnel[i + 1];
                    const dropPct =
                      next && d.count > 0
                        ? Math.round(((d.count - next.count) / d.count) * 100)
                        : null;
                    const isLeak = dropPct !== null && dropPct >= 35;
                    return (
                      <div key={d.name} className={styles.fnStage}>
                        <div className={styles.fnStageName}>{d.name}</div>
                        <div className={styles.fnStageCount}>{d.count.toLocaleString()}</div>
                        <div className={`${styles.fnStagePct} ${isLeak ? styles.leak : ""}`}>
                          {dropPct !== null ? `−${dropPct}% to next` : "→ hired"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>

            {/* ENGAGEMENT */}
            <section className={styles.section}>
              <div className={styles.sectionHead}>
                <div>
                  <div className={styles.sectionEyebrow}>Feature pulse · this week</div>
                  <div className={styles.sectionTitle}>What learners are actually using.</div>
                  <div className={styles.sectionSub}>
                    Hot tiles are pulling weight. Cold tiles are either underused features or
                    signals that learners are stuck.
                  </div>
                </div>
              </div>
              <div className={styles.engageCard}>
                <div className={styles.engageGrid}>
                  {data.features.map((f) => {
                    const max = Math.max(...f.bars, 1);
                    return (
                      <div
                        key={f.feature_key}
                        className={`${styles.egTile} ${f.cold ? styles.cold : ""}`}
                      >
                        <div className={styles.egIcon}>
                          <FeatureIcon featureKey={f.feature_key} />
                        </div>
                        <div className={styles.egName}>{f.name}</div>
                        <div className={styles.egCount}>{f.count}</div>
                        <div className={styles.egSub}>{f.sub}</div>
                        <div className={styles.egBars}>
                          {f.bars.map((b, i) => (
                            <div
                              key={i}
                              className={styles.egBar}
                              style={{ height: `${(b / max) * 100}%` }}
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>

            {/* STUDENT TABLE */}
            <section className={styles.section} id="studentSection">
              <div className={styles.sectionHead}>
                <div>
                  <div className={styles.sectionEyebrow}>
                    All learners · {students.length} active
                  </div>
                  <div className={styles.sectionTitle}>Student roster, sorted by risk.</div>
                  <div className={styles.sectionSub}>
                    Click any row to open the full timeline. Sort columns to triage. Search to
                    find a specific learner.
                  </div>
                </div>
              </div>
              <div className={styles.tableCard}>
                <div className={styles.tableToolbar}>
                  <div className={styles.ttFilter}>
                    {(
                      [
                        ["all", "All"],
                        ["severe", "Severe risk"],
                        ["high", "High risk"],
                        ["paid-stalled", "Paid + stalled"],
                        ["thriving", "Thriving"],
                        ["new", "Joined < 7d"],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        className={`${styles.filterChip} ${filter === key ? styles.on : ""}`}
                        onClick={() => setFilter(key)}
                      >
                        {label}
                        {key === "all" && (
                          <span className={styles.ttCount}>{students.length}</span>
                        )}
                      </button>
                    ))}
                  </div>
                  <div className={styles.ttSearch}>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8" />
                      <path d="m21 21-4.3-4.3" />
                    </svg>
                    <input
                      type="search"
                      aria-label="Search students"
                      placeholder="Search by name…"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                    />
                  </div>
                </div>
                <div style={{ overflowX: "auto" }}>
                  <table className={styles.studentsTable}>
                    <thead>
                      <tr>
                        {(
                          [
                            ["name", "Student"],
                            ["role", "Track"],
                            ["stage", "Stage"],
                            ["progress", "Progress"],
                            ["streak", "Streak"],
                            ["last", "Last seen"],
                            ["risk", "Risk"],
                          ] as const
                        ).map(([key, label]) => (
                          <th
                            key={key}
                            className={sort.key === key ? styles.sorted : ""}
                            onClick={() => onSortClick(key)}
                          >
                            {label}{" "}
                            <span className={styles.sortArrow}>
                              {sort.dir === "asc" ? "↑" : "↓"}
                            </span>
                          </th>
                        ))}
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.length === 0 ? (
                        <tr>
                          <td colSpan={8}>
                            <div className={styles.emptyState}>
                              <b>No students match.</b>
                              <span>Try a different filter or clear the search.</span>
                            </div>
                          </td>
                        </tr>
                      ) : (
                        filtered.map((s) => (
                          <tr key={s.id} onClick={() => setOpenStudentId(s.id)}>
                            <td>
                              <div className={styles.trName}>
                                <div
                                  className={styles.trAvatar}
                                  style={{ background: avatarBg(s.id) }}
                                >
                                  {initials(s.name)}
                                </div>
                                <div>
                                  <b>{s.name}</b>
                                  <span>Joined {s.joined}</span>
                                </div>
                              </div>
                            </td>
                            <td>
                              <span className={styles.trRole}>{s.track}</span>
                            </td>
                            <td>
                              <span
                                className={`${styles.trStage} ${
                                  styles[s.stage.toLowerCase() as keyof typeof styles] ?? ""
                                }`}
                              >
                                {s.stage}
                              </span>
                            </td>
                            <td>
                              <div className={styles.trProgress}>
                                <div className={styles.trBar}>
                                  <div
                                    className={styles.trBarFill}
                                    style={{ width: `${s.progress}%` }}
                                  />
                                </div>
                                <span className={styles.trPct}>{s.progress}%</span>
                              </div>
                            </td>
                            <td>
                              <span className={styles.trNum}>{s.streak}d</span>
                            </td>
                            <td>
                              <span
                                className={`${styles.trLast} ${
                                  s.last_seen >= 7 ? styles.stale : ""
                                }`}
                              >
                                {lastSeenText(s.last_seen)}
                              </span>
                            </td>
                            <td>
                              <span
                                className={`${styles.riskPill} ${
                                  styles[riskTier(s.risk)]
                                }`}
                              >
                                <span className={styles.riskDot} />
                                {s.risk} · {riskLabel(s.risk)}
                              </span>
                            </td>
                            <td>
                              <button
                                className={styles.trActionBtn}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setOpenStudentId(s.id);
                                }}
                              >
                                Open
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </main>

          {/* RIGHT RAIL */}
          <aside className={styles.rightRail}>
            <div className={styles.rrCard}>
              <div className={styles.rrHead}>
                <div>
                  <div className={styles.rrEyebrow}>Today&apos;s calls</div>
                  <div className={styles.rrTitle}>{data.calls.length} calls scheduled.</div>
                </div>
              </div>
              <div className={styles.callList}>
                {data.calls.map((c) => {
                  const s = students.find((st) => st.id === c.student_id);
                  return (
                    <div
                      key={c.student_id + c.time}
                      className={styles.callItem}
                      onClick={() => setOpenStudentId(c.student_id)}
                    >
                      <div className={styles.callTime}>{c.time}</div>
                      <div className={styles.callInfo}>
                        <div className={styles.callName}>{s?.name ?? "—"}</div>
                        <div className={styles.callReason}>{c.reason}</div>
                      </div>
                      <div className={styles.callGo}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M5 12h14M13 6l6 6-6 6" />
                        </svg>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className={styles.rrCard}>
              <div className={styles.rrHead}>
                <div>
                  <div className={styles.rrEyebrow}>Live event feed</div>
                  <div className={styles.rrTitle}>What just happened.</div>
                </div>
              </div>
              <div className={styles.eventFeed}>
                {data.events.map((e, i) => (
                  <div key={i} className={styles.event}>
                    <div className={styles.eventTime}>{e.time_label}</div>
                    <div className={styles.eventContent}>
                      <span
                        className={`${styles.eventTag} ${
                          styles[e.kind as keyof typeof styles] ?? ""
                        }`}
                      >
                        {TAG_LABELS[e.kind] ?? e.kind}
                      </span>
                      <span dangerouslySetInnerHTML={{ __html: e.text }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.rrCard}>
              <div className={styles.rrHead}>
                <div>
                  <div className={styles.rrEyebrow}>Revenue · this month</div>
                  <div className={styles.rrTitle}>{data.revenue.month_total}</div>
                </div>
              </div>
              <div className={styles.revenueMini}>
                <div className={styles.revRow}>
                  <span className={styles.revLabel}>New purchases</span>
                  <span className={styles.revVal}>{data.revenue.new_purchases}</span>
                </div>
                <div className={styles.revRow}>
                  <span className={styles.revLabel}>Renewals</span>
                  <span className={styles.revVal}>{data.revenue.renewals}</span>
                </div>
                <div className={styles.revRow}>
                  <span className={styles.revLabel}>Refunds</span>
                  <span className={styles.revVal}>{data.revenue.refunds}</span>
                </div>
              </div>
              <RevenueChart spark={data.revenue.spark} />
            </div>
          </aside>
        </div>
      )}

      {/* MODAL */}
      <StudentModal
        student={openStudent}
        onClose={() => setOpenStudentId(null)}
      />
    </div>
  );
}

// ── Funnel ──────────────────────────────────────────────────────────────

function FunnelChart({ stages }: { stages: FunnelStage[] }) {
  if (stages.length < 2) return null;
  const W = 1100;
  const H = 220;
  const PAD_X = 30;
  const PAD_Y = 20;
  const innerW = W - PAD_X * 2;
  const segW = innerW / (stages.length - 1);
  const max = stages[0].count || 1;
  const cy = H / 2;
  const maxHalf = (H - PAD_Y * 2) / 2;
  return (
    <svg className={styles.funnelSvg} viewBox={`0 0 ${W} ${H}`} xmlns="http://www.w3.org/2000/svg">
      <defs>
        {stages.map((_, i) => {
          if (i >= stages.length - 1) return null;
          const isWarm = i >= 4;
          return (
            <linearGradient key={i} id={`fnG${i}`} x1="0%" x2="100%">
              <stop
                offset="0%"
                stopColor={isWarm ? "#d6a54d" : "#5fa37f"}
                stopOpacity="0.85"
              />
              <stop
                offset="100%"
                stopColor={isWarm ? "#b8862d" : "#356d50"}
                stopOpacity="0.78"
              />
            </linearGradient>
          );
        })}
      </defs>
      {stages.map((d, i) => {
        if (i >= stages.length - 1) return null;
        const next = stages[i + 1];
        const x1 = PAD_X + i * segW;
        const x2 = PAD_X + (i + 1) * segW;
        const h1 = maxHalf * (d.count / max);
        const h2 = maxHalf * (next.count / max);
        return (
          <path
            key={`p${i}`}
            d={`M ${x1} ${cy - h1} L ${x2} ${cy - h2} L ${x2} ${cy + h2} L ${x1} ${cy + h1} Z`}
            fill={`url(#fnG${i})`}
          />
        );
      })}
      {stages.map((d, i) => {
        const x = PAD_X + i * segW;
        const ratio = d.count / max;
        const r = 14 + ratio * 8;
        const isLast = i === stages.length - 1;
        const fillColor = isLast ? "#d6a54d" : "#1a2620";
        const textColor = isLast ? "#1a2620" : "#fff";
        const label = d.count > 999 ? (d.count / 1000).toFixed(1) + "k" : String(d.count);
        return (
          <g key={`g${i}`}>
            <circle cx={x} cy={cy} r={r} fill={fillColor} stroke="#fff" strokeWidth={2} />
            <text
              x={x}
              y={cy + 4}
              textAnchor="middle"
              fill={textColor}
              fontSize="11"
              fontWeight="700"
              fontFamily="JetBrains Mono"
            >
              {label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Revenue chart ───────────────────────────────────────────────────────

function RevenueChart({ spark }: { spark: number[] }) {
  if (!spark.length) return <svg className={styles.revChart} viewBox="0 0 280 90" />;
  const W = 280;
  const H = 90;
  const max = Math.max(...spark);
  const min = Math.min(...spark);
  const range = max - min || 1;
  const step = W / Math.max(1, spark.length - 1);
  const pts = spark.map((v, i) => [i * step, H - ((v - min) / range) * (H - 14) - 6] as const);
  const line = "M " + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ");
  const area =
    `M 0,${H} L ` +
    pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" L ") +
    ` L ${W},${H} Z`;
  return (
    <svg className={styles.revChart} viewBox={`0 0 ${W} ${H}`} xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#5fa37f" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#5fa37f" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#revGrad)" />
      <path
        d={line}
        stroke="#5fa37f"
        strokeWidth={2}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={pts[pts.length - 1][0]}
        cy={pts[pts.length - 1][1]}
        r={3.5}
        fill="#5fa37f"
      />
    </svg>
  );
}

// ── Feature icon helper ────────────────────────────────────────────────

function FeatureIcon({ featureKey }: { featureKey: string }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (featureKey) {
    case "flashcards":
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="14" rx="2" />
          <path d="M3 10h18" />
        </svg>
      );
    case "agent_q":
      return (
        <svg {...common}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case "senior_reviews":
      return (
        <svg {...common}>
          <polyline points="20 6 9 17 4 12" />
        </svg>
      );
    case "notes":
      return (
        <svg {...common}>
          <path d="M14 3v4a1 1 0 0 0 1 1h4" />
          <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" />
        </svg>
      );
    case "labs":
      return (
        <svg {...common}>
          <path d="M10 2v7.31L5.7 16H18.3L14 9.31V2" />
          <path d="M8.5 2h7" />
        </svg>
      );
    case "capstones":
      return (
        <svg {...common}>
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
        </svg>
      );
    case "jd_match":
      return (
        <svg {...common}>
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
      );
    case "interview":
      return (
        <svg {...common}>
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="10" />
        </svg>
      );
  }
}

// ── Modal ───────────────────────────────────────────────────────────────

interface TimelineEvent {
  time: string;
  text: string;
  cls?: "danger" | "gold";
}
function buildTimeline(s: ConsoleStudent): TimelineEvent[] {
  if (s.risk >= 75) {
    return [
      { time: "today", text: "<b>No activity.</b>", cls: "danger" },
      {
        time: `${s.last_seen}d ago`,
        text: `Last login — opened <b>${s.stage}</b> for 4 minutes, no actions taken.`,
        cls: "danger",
      },
      {
        time: `${s.last_seen + 3}d ago`,
        text: "Failed Lab B test cases on third attempt. Did not request review.",
      },
      {
        time: `${s.last_seen + 5}d ago`,
        text: 'Asked agent: <i>"why does my retry decorator not work"</i>',
      },
      {
        time: `${s.last_seen + 9}d ago`,
        text: "Streak broken (was 6d).",
        cls: "danger",
      },
      {
        time: `${s.last_seen + 12}d ago`,
        text: `Purchased <b>${s.track}</b> track ($89).`,
        cls: "gold",
      },
      { time: `Joined ${s.joined}`, text: "Account created." },
    ];
  }
  if (s.risk >= 50) {
    return [
      { time: "today", text: `Opened <b>${s.stage}</b>, completed 1 flashcard set.` },
      { time: "2d ago", text: "Asked agent 2 questions about async retry logic." },
      { time: "4d ago", text: "Submitted Lab A — passed 4/5 tests." },
      { time: "6d ago", text: "Streak dropped from 5d to 1d.", cls: "danger" },
      { time: "9d ago", text: "Capstone draft started." },
      {
        time: "14d ago",
        text: "Promoted from <b>Onboarding</b> to <b>Today</b>.",
        cls: "gold",
      },
      { time: `Joined ${s.joined}`, text: "Account created." },
    ];
  }
  if (s.risk < 30) {
    return [
      { time: "today", text: `Completed Lesson 4 · <b>+5%</b> readiness.` },
      { time: "today", text: "Submitted senior review on rate-limit lab." },
      {
        time: "1d ago",
        text: `<b>${s.flashcards} flashcards</b> reviewed across 2 sessions.`,
      },
      { time: "2d ago", text: `Asked agent about <i>vector embeddings</i>.` },
      {
        time: "3d ago",
        text: `Capstone draft milestone — Production readiness <b>72</b>.`,
        cls: "gold",
      },
      { time: "5d ago", text: `Streak reached <b>${s.streak}d</b>.`, cls: "gold" },
      { time: `Joined ${s.joined}`, text: "Account created." },
    ];
  }
  return [
    { time: "today", text: `Completed warm-up · ${(s.flashcards % 8) + 4} cards.` },
    { time: "1d ago", text: `Worked through Lab B for 35 min.` },
    { time: "3d ago", text: "Submitted reflection note." },
    { time: "5d ago", text: `Asked agent ${Math.max(1, s.agent_q - 3)} questions.` },
    { time: "1w ago", text: `Started ${s.stage} phase.` },
    { time: `Joined ${s.joined}`, text: "Account created." },
  ];
}

function StudentModal({
  student,
  onClose,
}: {
  student: ConsoleStudent | null;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!student) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [student, onClose]);

  if (!student) {
    return <div className={styles.modalBackdrop} aria-hidden />;
  }
  const timeline = buildTimeline(student);
  const tier = riskTier(student.risk);
  return (
    <div className={`${styles.modalBackdrop} ${styles.open}`} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHead}>
          <div className={styles.mhAvatar} style={{ background: avatarBg(student.id) }}>
            {initials(student.name)}
          </div>
          <div>
            <div className={styles.mhName}>{student.name}</div>
            <div className={styles.mhMeta}>
              <span>{student.track}</span>
              <span className="dot" />
              <span>{student.stage}</span>
              <span className="dot" />
              <span>Joined {student.joined}</span>
              <span className="dot" />
              <span>
                {student.paid
                  ? `Paid · ${student.purchases > 1 ? "2 tracks" : "1 track"}`
                  : "Free tier"}
              </span>
            </div>
          </div>
          <button className={styles.mhClose} onClick={onClose} aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className={styles.modalBody}>
          <div className={styles.mbGrid}>
            <Stat
              label="Risk"
              value={String(student.risk)}
              sub={riskLabel(student.risk)}
              danger={tier === "severe" || tier === "high"}
            />
            <Stat
              label="Progress"
              value={`${student.progress}%`}
              sub="to next role"
            />
            <Stat
              label="Streak"
              value={`${student.streak}d`}
              sub={
                student.streak > 5
                  ? "strong"
                  : student.streak > 0
                  ? "building"
                  : "broken"
              }
            />
            <Stat
              label="Last seen"
              value={lastSeenText(student.last_seen)}
              sub={`${student.sessions14} sessions · 14d`}
              danger={student.last_seen >= 7}
            />
          </div>

          <div className={styles.mbSection}>
            <div className={styles.mbSectionTitle}>Platform usage · last 14 days</div>
            <div className={styles.usageGrid}>
              <UsageTile num={student.flashcards} name="Flashcards reviewed" />
              <UsageTile num={student.agent_q} name="Agent questions" />
              <UsageTile num={student.reviews} name="Senior reviews" />
              <UsageTile num={student.notes} name="Notes graduated" />
              <UsageTile num={student.labs} name="Labs completed" />
              <UsageTile num={student.capstones} name="Capstones shipped" />
            </div>
          </div>

          <div className={styles.mbSection}>
            <div className={styles.mbSectionTitle}>Activity timeline</div>
            <div style={{ position: "relative", paddingLeft: 18 }}>
              <div
                style={{
                  position: "absolute",
                  left: 5,
                  top: 8,
                  bottom: 8,
                  width: 1,
                  background: "var(--line-2)",
                }}
              />
              {timeline.map((t, i) => (
                <div
                  key={i}
                  style={{
                    position: "relative",
                    padding: "8px 0 12px",
                    display: "flex",
                    gap: 14,
                    fontSize: 12,
                  }}
                >
                  <div
                    style={{
                      position: "absolute",
                      left: -18,
                      top: 13,
                      width: 11,
                      height: 11,
                      borderRadius: "50%",
                      background: "var(--panel)",
                      border: `2px solid ${
                        t.cls === "danger"
                          ? "var(--red-2)"
                          : t.cls === "gold"
                          ? "var(--gold)"
                          : "var(--forest-3)"
                      }`,
                    }}
                  />
                  <div
                    style={{
                      fontFamily: "var(--mono)",
                      fontSize: 11,
                      color: "var(--muted)",
                      minWidth: 90,
                    }}
                  >
                    {t.time}
                  </div>
                  <div
                    style={{ color: "var(--ink-2)", lineHeight: 1.5 }}
                    dangerouslySetInnerHTML={{ __html: t.text }}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className={styles.modalFoot}>
          <button className={`${styles.btn} ${styles.ghost}`}>Send DM</button>
          <button className={`${styles.btn} ${styles.ghost}`}>Add note</button>
          <button className={`${styles.btn} ${styles.primary}`}>Schedule call</button>
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  danger = false,
}: {
  label: string;
  value: string;
  sub: string;
  danger?: boolean;
}) {
  return (
    <div className={styles.mbStat}>
      <div className={styles.mbStatLabel}>{label}</div>
      <div className={`${styles.mbStatVal} ${danger ? styles.danger : ""}`}>{value}</div>
      <div className={styles.mbStatSub}>{sub}</div>
    </div>
  );
}

function UsageTile({ num, name }: { num: number; name: string }) {
  return (
    <div className={styles.usageTile}>
      <div className={styles.usageNum}>{num}</div>
      <div className={styles.usageName}>{name}</div>
    </div>
  );
}
