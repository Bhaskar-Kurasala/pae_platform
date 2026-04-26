"use client";

import { useState } from "react";

import { useFreeEnroll } from "@/lib/hooks/use-payments";
import { v8Toast } from "@/components/v8/v8-toast";

import type { CheckoutButtonVariant } from "./checkout-button";

export interface FreeEnrollButtonProps {
  courseId: string;
  label: string;
  variant?: CheckoutButtonVariant;
  className?: string;
  disabled?: boolean;
  onEnrolled?: (courseId: string) => void;
  onError?: (err: Error) => void;
}

export function FreeEnrollButton(props: FreeEnrollButtonProps) {
  const {
    courseId,
    label,
    variant = "default",
    className,
    disabled,
    onEnrolled,
    onError,
  } = props;

  const enroll = useFreeEnroll();
  const [working, setWorking] = useState(false);

  const handleClick = () => {
    if (working) return;
    setWorking(true);
    enroll
      .mutateAsync({ course_id: courseId })
      .then((res) => {
        v8Toast("Enrolled.");
        onEnrolled?.(res.course_id);
      })
      .catch((err: unknown) => {
        const e = err instanceof Error ? err : new Error("Enroll failed");
        onError?.(e);
      })
      .finally(() => setWorking(false));
  };

  const buttonClass = [className, `variant-${variant}`]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type="button"
      className={buttonClass}
      data-variant={variant}
      onClick={handleClick}
      disabled={disabled || working}
      aria-busy={working || undefined}
    >
      {working ? "Working…" : label}
    </button>
  );
}
