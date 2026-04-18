"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

export interface TextareaProps extends React.ComponentProps<"textarea"> {
  /** Auto-grow with content up to `maxRows`. Default: off. */
  autosize?: boolean;
  /** Cap for autosize. Default 8. */
  maxRows?: number;
  /** Show "current/max" character counter beneath the textarea. Requires maxLength. */
  showCounter?: boolean;
  /** Visual error state — also sets aria-invalid. */
  invalid?: boolean;
}

const textareaClass = cn(
  "w-full min-w-0 rounded-lg border border-input bg-transparent px-3 py-2 text-base",
  "outline-none placeholder:text-muted-foreground resize-y",
  "transition-[border-color,box-shadow] duration-fast ease-out-quad",
  "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
  "disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50",
  "aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20",
  "md:text-sm dark:bg-input/30 dark:disabled:bg-input/80",
  "dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40",
);

function autosizeFit(el: HTMLTextAreaElement, maxRows: number): void {
  const style = window.getComputedStyle(el);
  const lineHeight = parseFloat(style.lineHeight) || 20;
  const paddingY =
    parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
  const borderY =
    parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
  el.style.height = "auto";
  const contentH = el.scrollHeight - paddingY;
  const maxH = lineHeight * maxRows + paddingY + borderY;
  const newH = Math.min(el.scrollHeight, maxH);
  el.style.height = `${newH}px`;
  el.style.overflowY = contentH > lineHeight * maxRows ? "auto" : "hidden";
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    {
      className,
      autosize = false,
      maxRows = 8,
      showCounter = false,
      invalid,
      "aria-invalid": ariaInvalid,
      maxLength,
      rows = 3,
      value,
      defaultValue,
      onChange,
      ...props
    },
    forwardedRef,
  ) {
    const innerRef = React.useRef<HTMLTextAreaElement | null>(null);
    const setRefs = React.useCallback(
      (el: HTMLTextAreaElement | null) => {
        innerRef.current = el;
        if (typeof forwardedRef === "function") forwardedRef(el);
        else if (forwardedRef) forwardedRef.current = el;
      },
      [forwardedRef],
    );

    React.useEffect(() => {
      if (!autosize || !innerRef.current) return;
      autosizeFit(innerRef.current, maxRows);
    }, [autosize, maxRows, value]);

    const [internalValue, setInternalValue] = React.useState(
      defaultValue?.toString() ?? "",
    );
    const currentLength =
      value !== undefined
        ? String(value).length
        : internalValue.length;

    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      if (value === undefined) setInternalValue(e.target.value);
      if (autosize && innerRef.current) autosizeFit(innerRef.current, maxRows);
      onChange?.(e);
    };

    return (
      <div className="w-full">
        <textarea
          ref={setRefs}
          rows={rows}
          maxLength={maxLength}
          value={value}
          defaultValue={defaultValue}
          onChange={handleChange}
          data-slot="textarea"
          aria-invalid={ariaInvalid ?? invalid}
          className={cn(textareaClass, autosize && "resize-none", className)}
          {...props}
        />
        {showCounter && maxLength ? (
          <div className="mt-1 flex justify-end">
            <span
              className={cn(
                "text-[11px] tabular-nums text-muted-foreground",
                currentLength > maxLength * 0.9 && "text-amber-500",
                currentLength >= maxLength && "text-destructive",
              )}
              aria-live="polite"
            >
              {currentLength}/{maxLength}
            </span>
          </div>
        ) : null}
      </div>
    );
  },
);

export { Textarea };
