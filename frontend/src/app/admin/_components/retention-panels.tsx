"use client";

/**
 * RETENTION-V2 — compact metric strip + "Most urgent" panel.
 *
 * Replaces the bulky six-panel layout. Two sections:
 *   A) Metric strip — one tile per slip pattern, click → onSeeAll(slip_type).
 *   B) "Most urgent" — top-N students by risk_score across ALL slip types,
 *      deduped by user_id. Click row → onOpenStudent(user_id).
 *
 * Reads from /api/v1/admin/most-urgent-students (RETENTION-V2 endpoint).
 * The legacy useRiskPanels hook is preserved — the cockpit still uses it
 * for slipUserIds bucketing in the roster view.
 */

import { useMostUrgentStudents, type MostUrgentTile } from "@/lib/hooks/use-admin";
import { useAdminTheme } from "@/lib/hooks/use-admin-theme";

interface RetentionPanelsProps {
  onSeeAll?: (slipKey: string) => void;
  onOpenStudent?: (studentId: string) => void;
}

type Tone = "danger" | "warn" | "info" | "neutral";

const TONE_COLOR: Record<Tone, string> = {
  danger: "#d96252",
  warn: "#d6a54d",
  info: "#356d50",
  neutral: "#8f897d",
};

function toneColor(t: string): string {
  return TONE_COLOR[(t as Tone) in TONE_COLOR ? (t as Tone) : "neutral"];
}

function avatarLabel(name: string): string {
  return (
    name
      .split(" ")
      .map((w) => w[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}

function Tile({
  tile,
  onClick,
  isDark,
}: {
  tile: MostUrgentTile;
  onClick?: () => void;
  isDark: boolean;
}) {
  const empty = tile.count === 0;
  const accent = empty ? TONE_COLOR.neutral : toneColor(tile.tone);
  const bg = isDark ? "#1d2a23" : "#fbfaf6";
  const border = isDark ? "#2a3a30" : "#e8e3d6";
  const textMain = isDark ? "#f3efe5" : "#2a2a2a";
  const textMuted = isDark ? "#a8a496" : "#6f6a5f";
  return (
    <button
      type="button"
      onClick={onClick}
      className="ret-tile"
      style={{
        background: bg,
        border: `1px solid ${border}`,
        boxShadow: empty ? "none" : `inset 4px 0 0 0 ${accent}`,
        color: textMain,
      }}
    >
      <div
        className="ret-tile-eyebrow"
        style={{ color: empty ? textMuted : accent }}
      >
        {tile.label}
      </div>
      <div
        className="ret-tile-count"
        style={{ color: empty ? textMuted : textMain }}
      >
        {tile.count}
      </div>
      <div className="ret-tile-desc" style={{ color: textMuted }}>
        {tile.description}
      </div>
    </button>
  );
}

export function RetentionPanels({
  onSeeAll,
  onOpenStudent,
}: RetentionPanelsProps = {}) {
  const { theme } = useAdminTheme();
  const isDark = theme === "dark";
  const { data, isLoading, isError, error } = useMostUrgentStudents(5);

  const surface = isDark ? "#1d2a23" : "#fbfaf6";
  const border = isDark ? "#2a3a30" : "#e8e3d6";
  const textMain = isDark ? "#f3efe5" : "#2a2a2a";
  const textMuted = isDark ? "#a8a496" : "#6f6a5f";
  const rowBg = isDark ? "#243329" : "#fffdf7";
  const rowBorder = isDark ? "#2f3f35" : "#ece7d8";

  const styleBlock = (
    <style>{`
      .ret-strip {
        display: grid;
        grid-template-columns: repeat(2, minmax(0,1fr));
        gap: 10px;
        margin-bottom: 16px;
      }
      @media (min-width: 768px) {
        .ret-strip { grid-template-columns: repeat(3, minmax(0,1fr)); }
      }
      @media (min-width: 1024px) {
        .ret-strip { grid-template-columns: repeat(6, minmax(0,1fr)); }
      }
      .ret-tile {
        text-align: left;
        padding: 12px 14px;
        border-radius: 10px;
        cursor: pointer;
        transition: transform 120ms ease, box-shadow 120ms ease;
        font-family: Inter, system-ui, sans-serif;
        display: flex;
        flex-direction: column;
        gap: 4px;
        min-height: 88px;
      }
      .ret-tile:hover { transform: translateY(-1px); }
      .ret-tile-eyebrow {
        font: 700 10px/1.2 Inter, system-ui, sans-serif;
        text-transform: uppercase;
        letter-spacing: 0.18em;
      }
      .ret-tile-count {
        font: 600 24px/1 'Fraunces', Georgia, serif;
        font-variant-numeric: tabular-nums;
      }
      .ret-tile-desc {
        font: 400 12px/1.35 Inter, system-ui, sans-serif;
      }
      .ret-card {
        border-radius: 12px;
        padding: 16px 18px;
      }
      .ret-card-title {
        font: 600 18px/1.2 'Fraunces', Georgia, serif;
      }
      .ret-card-sub {
        font: 400 12px/1.4 Inter, system-ui, sans-serif;
      }
      .ret-see-all-link {
        font: 600 12px/1.2 Inter, system-ui, sans-serif;
        background: transparent;
        border: none;
        cursor: pointer;
        padding: 4px 6px;
      }
      .ret-see-all-link:hover { text-decoration: underline; }
      .ret-row {
        width: 100%;
        text-align: left;
        display: grid;
        grid-template-columns: 36px minmax(0,1fr) auto auto auto auto;
        align-items: center;
        gap: 12px;
        padding: 10px 12px;
        border-radius: 10px;
        cursor: pointer;
        transition: background 120ms ease;
      }
      .ret-row + .ret-row { margin-top: 6px; }
      .ret-row:hover { filter: brightness(1.03); }
      .ret-avatar {
        width: 32px; height: 32px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font: 700 11px/1 Inter, system-ui, sans-serif;
        color: #fffdf7;
        background: #8f897d;
      }
      .ret-name {
        font: 600 13px/1.2 Inter, system-ui, sans-serif;
      }
      .ret-email {
        font: 400 11px/1.3 Inter, system-ui, sans-serif;
        margin-top: 2px;
      }
      .ret-pill {
        font: 700 10px/1 Inter, system-ui, sans-serif;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        padding: 4px 8px;
        border-radius: 999px;
      }
      .ret-score {
        font: 600 14px/1 'Fraunces', Georgia, serif;
        font-variant-numeric: tabular-nums;
        padding: 4px 8px;
        border-radius: 8px;
      }
      .ret-last {
        font: 400 11px/1.2 Inter, system-ui, sans-serif;
      }
      .ret-open {
        font: 700 11px/1 Inter, system-ui, sans-serif;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid currentColor;
        background: transparent;
        cursor: pointer;
      }
      .ret-empty {
        font: 400 13px/1.4 Inter, system-ui, sans-serif;
        text-align: center;
        padding: 24px 12px;
        border-radius: 10px;
        border: 1px dashed;
      }
    `}</style>
  );

  if (isLoading) {
    return (
      <section aria-label="Retention metric strip and most urgent students">
        {styleBlock}
        <div className="ret-strip">
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              style={{
                height: 88,
                borderRadius: 10,
                background: surface,
                border: `1px solid ${border}`,
                opacity: 0.6,
              }}
            />
          ))}
        </div>
        <div
          className="ret-card"
          style={{
            background: surface,
            border: `1px solid ${border}`,
            color: textMuted,
          }}
        >
          Loading urgent students...
        </div>
      </section>
    );
  }

  if (isError || !data) {
    return (
      <section aria-label="Retention metric strip and most urgent students">
        {styleBlock}
        <div
          className="ret-card"
          style={{
            background: surface,
            border: `1px solid ${toneColor("danger")}`,
            color: toneColor("danger"),
          }}
        >
          Failed to load retention data: {(error as Error)?.message ?? "unknown error"}
        </div>
      </section>
    );
  }

  // Map slip_type → tile tone, for color-coding student rows.
  const toneBySlip: Record<string, Tone> = {};
  for (const t of data.tiles) {
    toneBySlip[t.slip_type] = (t.tone as Tone) ?? "neutral";
  }

  const handleSeeAllClick = () => {
    // The "See all in roster below" link smooth-scrolls to the roster section.
    const el = document.getElementById("studentSection");
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <section aria-label="Retention metric strip and most urgent students">
      {styleBlock}

      {/* Section A — Metric strip */}
      <div className="ret-strip" role="list">
        {data.tiles.map((tile) => (
          <Tile
            key={tile.slip_type}
            tile={tile}
            isDark={isDark}
            onClick={() => onSeeAll?.(tile.slip_type)}
          />
        ))}
      </div>

      {/* Section B — Most urgent panel */}
      <div
        className="ret-card"
        style={{
          background: surface,
          border: `1px solid ${border}`,
          color: textMain,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
            marginBottom: 12,
          }}
        >
          <div>
            <div className="ret-card-title" style={{ color: textMain }}>
              Most urgent
            </div>
            <div className="ret-card-sub" style={{ color: textMuted }}>
              Top {data.students.length || 5} across all slip patterns
            </div>
          </div>
          <button
            type="button"
            className="ret-see-all-link"
            onClick={handleSeeAllClick}
            style={{ color: toneColor("info") }}
          >
            See all in roster below ↓
          </button>
        </div>

        {data.students.length === 0 ? (
          <div
            className="ret-empty"
            style={{ borderColor: rowBorder, color: textMuted }}
          >
            No urgent students right now. Roster sorted by risk is below ↓
          </div>
        ) : (
          <div>
            {data.students.map((s) => {
              const tone = toneBySlip[s.slip_type] ?? "neutral";
              const accent = toneColor(tone);
              return (
                <div
                  key={s.user_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onOpenStudent?.(s.user_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onOpenStudent?.(s.user_id);
                    }
                  }}
                  className="ret-row"
                  style={{
                    background: rowBg,
                    border: `1px solid ${rowBorder}`,
                  }}
                >
                  <div className="ret-avatar">{avatarLabel(s.name)}</div>
                  <div style={{ minWidth: 0 }}>
                    <div
                      className="ret-name"
                      style={{
                        color: textMain,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {s.name}
                      {s.paid && (
                        <span
                          className="ret-pill"
                          style={{
                            marginLeft: 8,
                            color: "#7c3aed",
                            background: isDark
                              ? "rgba(124,58,237,0.18)"
                              : "rgba(124,58,237,0.10)",
                          }}
                        >
                          Paid
                        </span>
                      )}
                    </div>
                    <div
                      className="ret-email"
                      style={{
                        color: textMuted,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {s.email}
                    </div>
                  </div>
                  <span
                    className="ret-pill"
                    style={{
                      color: accent,
                      background: isDark
                        ? `${accent}26`
                        : `${accent}1f`,
                    }}
                  >
                    {s.slip_type.replace(/_/g, " ")}
                  </span>
                  <span
                    className="ret-score"
                    style={{
                      color: accent,
                      background: isDark
                        ? `${accent}1f`
                        : `${accent}14`,
                    }}
                    aria-label={`Risk score ${s.risk_score}`}
                  >
                    {Math.round(s.risk_score)}
                  </span>
                  <span className="ret-last" style={{ color: textMuted }}>
                    {s.last_active_text}
                  </span>
                  <button
                    type="button"
                    className="ret-open"
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenStudent?.(s.user_id);
                    }}
                    style={{ color: accent }}
                  >
                    Open
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
