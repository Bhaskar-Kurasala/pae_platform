"use client";

import { useRazorpayCheckout } from "./use-razorpay-checkout";

export type CheckoutButtonVariant = "gold" | "default" | "primary";

export interface RazorpayCheckoutButtonProps {
  targetType: "course" | "bundle";
  targetId: string;
  label: string;
  /** Visual treatment. Defaults to "default". */
  variant?: CheckoutButtonVariant;
  className?: string;
  /** Disable the CTA externally (e.g. while parent is loading). */
  disabled?: boolean;
  onUnlocked?: (entitlementCourseIds: string[]) => void;
  onCancel?: () => void;
  onError?: (err: Error) => void;
}

export function RazorpayCheckoutButton(props: RazorpayCheckoutButtonProps) {
  const {
    targetType,
    targetId,
    label,
    variant = "default",
    className,
    disabled,
    onUnlocked,
    onCancel,
    onError,
  } = props;

  const { startCheckout, isWorking } = useRazorpayCheckout();

  const handleClick = () => {
    void startCheckout({
      targetType,
      targetId,
      onSuccess: onUnlocked,
      onCancel,
      onError,
    });
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
      disabled={disabled || isWorking}
      aria-busy={isWorking || undefined}
    >
      {isWorking ? "Working…" : label}
    </button>
  );
}
