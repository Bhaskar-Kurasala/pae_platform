"use client";

import * as React from "react";
import {
  Controller,
  FormProvider,
  useFormContext,
  type ControllerProps,
  type ControllerRenderProps,
  type ControllerFieldState,
  type FieldPath,
  type FieldValues,
  type UseFormReturn,
} from "react-hook-form";
import { cn } from "@/lib/utils";
import { Label } from "@/components/ui/label";

/**
 * Form system — thin layer over react-hook-form + zod.
 *
 * Why the wrapper:
 *  - enforce uniform field layout (label, control, description, error)
 *  - provide a single <FormField> API that renders the full stack
 *  - keep RHF/Zod details at the form root; field callsites stay terse
 *
 * Usage:
 *   const form = useForm<Schema>({ resolver: zodResolver(schema) })
 *   <Form {...form} onSubmit={form.handleSubmit(onSubmit)}>
 *     <FormField name="email" label="Email" description="We'll never share it.">
 *       {(f) => <Input {...f} type="email" />}
 *     </FormField>
 *   </Form>
 */

export interface FormProps<TValues extends FieldValues>
  extends Omit<React.ComponentProps<"form">, "onSubmit"> {
  onSubmit?: React.ComponentProps<"form">["onSubmit"];
  form: UseFormReturn<TValues>;
}

export function Form<TValues extends FieldValues>({
  form,
  className,
  children,
  ...props
}: FormProps<TValues>) {
  return (
    <FormProvider {...form}>
      <form className={cn("space-y-4", className)} {...props}>
        {children}
      </form>
    </FormProvider>
  );
}

// ─── FormField ─────────────────────────────────────────────────

export interface FormFieldProps<
  TValues extends FieldValues,
  TName extends FieldPath<TValues>,
> extends Omit<ControllerProps<TValues, TName>, "render"> {
  label?: React.ReactNode;
  description?: React.ReactNode;
  /** Visually hidden label for accessibility. */
  labelHidden?: boolean;
  /** Wrapper className for the whole field stack. */
  className?: string;
  /** Render prop receiving the field + field state. */
  children: (
    field: ControllerRenderProps<TValues, TName>,
    fieldState: ControllerFieldState,
  ) => React.ReactNode;
}

export function FormField<
  TValues extends FieldValues,
  TName extends FieldPath<TValues>,
>({
  label,
  description,
  labelHidden,
  className,
  children,
  ...controllerProps
}: FormFieldProps<TValues, TName>) {
  const id = React.useId();
  const descId = description ? `${id}-desc` : undefined;
  const errId = `${id}-err`;

  return (
    <Controller
      {...controllerProps}
      render={({ field, fieldState }) => (
        <div className={cn("space-y-1.5", className)}>
          {label ? (
            <Label
              htmlFor={id}
              className={cn(
                "text-sm font-medium",
                labelHidden && "sr-only",
                fieldState.error && "text-destructive",
              )}
            >
              {label}
            </Label>
          ) : null}
          {React.cloneElement(
            children(field, fieldState) as React.ReactElement,
            {
              id,
              "aria-invalid": Boolean(fieldState.error) || undefined,
              "aria-describedby":
                [descId, fieldState.error ? errId : undefined]
                  .filter(Boolean)
                  .join(" ") || undefined,
            } as Partial<
              React.HTMLAttributes<HTMLElement> & {
                id: string;
                "aria-invalid": boolean | undefined;
                "aria-describedby": string | undefined;
              }
            >,
          )}
          {description && !fieldState.error ? (
            <p id={descId} className="text-xs text-muted-foreground leading-relaxed">
              {description}
            </p>
          ) : null}
          {fieldState.error ? (
            <p
              id={errId}
              role="alert"
              className="text-xs text-destructive leading-relaxed"
            >
              {fieldState.error.message}
            </p>
          ) : null}
        </div>
      )}
    />
  );
}

/** Re-exports so callsites only import from one place. */
export {
  FormProvider,
  useFormContext,
  Controller,
  type FieldValues,
  type UseFormReturn,
};
