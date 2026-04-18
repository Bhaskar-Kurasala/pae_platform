"use client";

import * as React from "react";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useIsDesktop } from "@/lib/hooks/use-media-query";

/**
 * ResponsiveDialog — renders as a <Dialog /> on ≥sm breakpoint (640px)
 * and a bottom <Sheet /> on smaller screens.
 *
 * Same compound API. Callsites use the <ResponsiveDialog.*> parts and don't
 * need to worry about the underlying primitive.
 *
 * Usage:
 *   <ResponsiveDialog open={open} onOpenChange={setOpen}>
 *     <ResponsiveDialog.Trigger>...</ResponsiveDialog.Trigger>
 *     <ResponsiveDialog.Content>
 *       <ResponsiveDialog.Header>
 *         <ResponsiveDialog.Title>Edit goal</ResponsiveDialog.Title>
 *         <ResponsiveDialog.Description>...</ResponsiveDialog.Description>
 *       </ResponsiveDialog.Header>
 *       body
 *       <ResponsiveDialog.Footer>...</ResponsiveDialog.Footer>
 *     </ResponsiveDialog.Content>
 *   </ResponsiveDialog>
 */

type ModeContext = "dialog" | "sheet";
const Ctx = React.createContext<ModeContext>("dialog");

export interface ResponsiveDialogProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
  /** Force one mode regardless of viewport. Default: auto. */
  forceMode?: ModeContext;
}

export function ResponsiveDialog({
  open,
  defaultOpen,
  onOpenChange,
  children,
  forceMode,
}: ResponsiveDialogProps) {
  const isDesktop = useIsDesktop();
  const mode: ModeContext = forceMode ?? (isDesktop ? "dialog" : "sheet");

  const sharedProps = {
    open,
    defaultOpen,
    onOpenChange,
    children,
  };

  if (mode === "dialog") {
    return (
      <Ctx.Provider value="dialog">
        <Dialog {...sharedProps} />
      </Ctx.Provider>
    );
  }
  return (
    <Ctx.Provider value="sheet">
      <Sheet {...sharedProps} />
    </Ctx.Provider>
  );
}

function Trigger(props: React.ComponentProps<typeof DialogTrigger>) {
  const mode = React.useContext(Ctx);
  return mode === "dialog" ? <DialogTrigger {...props} /> : <SheetTrigger {...props} />;
}

export interface ResponsiveContentProps
  extends React.ComponentProps<typeof DialogContent> {
  /** Side for sheet mode. Default: "bottom". */
  side?: "top" | "right" | "bottom" | "left";
}

function Content({ side = "bottom", ...props }: ResponsiveContentProps) {
  const mode = React.useContext(Ctx);
  if (mode === "dialog") return <DialogContent {...props} />;
  return <SheetContent side={side} {...props} />;
}

function Header(props: React.ComponentProps<typeof DialogHeader>) {
  const mode = React.useContext(Ctx);
  return mode === "dialog" ? <DialogHeader {...props} /> : <SheetHeader {...props} />;
}

function Footer(props: React.ComponentProps<typeof DialogFooter>) {
  const mode = React.useContext(Ctx);
  return mode === "dialog" ? <DialogFooter {...props} /> : <SheetFooter {...props} />;
}

function Title(props: React.ComponentProps<typeof DialogTitle>) {
  const mode = React.useContext(Ctx);
  return mode === "dialog" ? <DialogTitle {...props} /> : <SheetTitle {...props} />;
}

function Description(props: React.ComponentProps<typeof DialogDescription>) {
  const mode = React.useContext(Ctx);
  return mode === "dialog" ? (
    <DialogDescription {...props} />
  ) : (
    <SheetDescription {...props} />
  );
}

function Close(props: React.ComponentProps<typeof DialogClose>) {
  const mode = React.useContext(Ctx);
  return mode === "dialog" ? <DialogClose {...props} /> : <SheetClose {...props} />;
}

ResponsiveDialog.Trigger = Trigger;
ResponsiveDialog.Content = Content;
ResponsiveDialog.Header = Header;
ResponsiveDialog.Footer = Footer;
ResponsiveDialog.Title = Title;
ResponsiveDialog.Description = Description;
ResponsiveDialog.Close = Close;
