"use client";

import * as React from "react";
import { Input as InputPrimitive } from "@base-ui/react/input";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface InputProps extends React.ComponentProps<"input"> {
  /** Icon/element rendered at the leading edge (inside the box). */
  leadingIcon?: React.ReactNode;
  /** Icon/element rendered at the trailing edge (inside the box). */
  trailingIcon?: React.ReactNode;
  /** When true and the input has a value, show a clear button (fires onClear). */
  clearable?: boolean;
  onClear?: () => void;
  /** Visual error state — also set aria-invalid. */
  invalid?: boolean;
}

const inputClass = cn(
  "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1 text-base",
  "outline-none placeholder:text-muted-foreground",
  "transition-[border-color,box-shadow] duration-fast ease-out-quad",
  "file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
  "disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50",
  "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
  "md:text-sm dark:bg-input/30 dark:disabled:bg-input/80",
  "dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
);

const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    className,
    type,
    leadingIcon,
    trailingIcon,
    clearable,
    onClear,
    invalid,
    value,
    defaultValue,
    "aria-invalid": ariaInvalid,
    ...props
  },
  ref,
) {
  const hasAddons = Boolean(leadingIcon || trailingIcon || clearable);
  const hasValue = value !== undefined ? String(value).length > 0 : undefined;

  if (!hasAddons) {
    return (
      <InputPrimitive
        ref={ref}
        type={type}
        data-slot="input"
        aria-invalid={ariaInvalid ?? invalid}
        className={cn(inputClass, className)}
        value={value}
        defaultValue={defaultValue}
        {...props}
      />
    );
  }

  return (
    <div
      data-slot="input-wrapper"
      data-invalid={invalid || ariaInvalid ? true : undefined}
      className={cn(
        "group relative flex h-8 w-full min-w-0 items-center rounded-lg border border-input bg-transparent",
        "transition-[border-color,box-shadow] duration-fast ease-out-quad",
        "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
        "data-[invalid=true]:border-destructive data-[invalid=true]:ring-3 data-[invalid=true]:ring-destructive/20",
        "dark:bg-input/30",
        className,
      )}
    >
      {leadingIcon ? (
        <span className="pl-2.5 text-muted-foreground pointer-events-none flex items-center">
          {leadingIcon}
        </span>
      ) : null}
      <InputPrimitive
        ref={ref}
        type={type}
        data-slot="input"
        aria-invalid={ariaInvalid ?? invalid}
        value={value}
        defaultValue={defaultValue}
        className={cn(
          "h-full flex-1 min-w-0 bg-transparent px-2.5 py-1 text-base outline-none",
          "placeholder:text-muted-foreground",
          leadingIcon ? "pl-2" : undefined,
          (clearable || trailingIcon) ? "pr-2" : undefined,
          "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
          "md:text-sm",
        )}
        {...props}
      />
      {clearable && hasValue && onClear ? (
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear input"
          className="mr-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors duration-fast"
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      ) : null}
      {trailingIcon && !(clearable && hasValue) ? (
        <span className="pr-2.5 text-muted-foreground pointer-events-none flex items-center">
          {trailingIcon}
        </span>
      ) : null}
    </div>
  );
});

export { Input };
