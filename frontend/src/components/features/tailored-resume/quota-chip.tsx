"use client";

import { tailoredResumeCopy as copy } from "@/lib/copy/tailored-resume";
import { useTailoredResumeQuota, type QuotaState } from "@/lib/hooks/use-tailored-resume";

interface QuotaChipProps {
  enabled?: boolean;
}

const DAILY_LIMIT = 5;
const MONTHLY_LIMIT = 20;

function chipLabel(quota: QuotaState | undefined): string {
  if (!quota) return "—";
  if (quota.reason === "first_resume_free") return copy.quota.chipFreeFirst;
  if (quota.reason === "daily_limit") return copy.quota.blockedDaily;
  if (quota.reason === "monthly_limit") return copy.quota.blockedMonthly;
  const usedToday = DAILY_LIMIT - quota.remaining_today;
  return copy.quota.chipWithin(usedToday, DAILY_LIMIT);
}

export function TailoredResumeQuotaChip({ enabled = true }: QuotaChipProps) {
  const { data, isLoading } = useTailoredResumeQuota(enabled);
  const quota = data?.quota;
  const blocked = quota?.allowed === false;

  return (
    <div
      className="rd-mini"
      data-quota-blocked={blocked ? "true" : "false"}
      title={
        quota
          ? copy.quota.chipMonth(MONTHLY_LIMIT - quota.remaining_month, MONTHLY_LIMIT)
          : ""
      }
    >
      <div className="k">Tailored resume quota</div>
      <div className="v">{isLoading ? "…" : chipLabel(quota)}</div>
      <div className="s">
        {blocked ? copy.quota.upgradeNudge : "First resume is always free."}
      </div>
    </div>
  );
}
