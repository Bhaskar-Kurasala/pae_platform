"use client";

import { type ReactNode, useRef } from "react";
import { motion, useInView, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";
import {
  MOTION,
  defaultTransition,
  fadeUpVariants,
  fadeVariants,
  scaleInVariants,
  slideLeftVariants,
  slideRightVariants,
  staggerParentVariants,
} from "@/lib/motion";

// Re-export MotionFade for a single import surface.
export { MotionFade } from "./motion-fade";

// ─── Shared types ──────────────────────────────────────────────
interface BaseMotionProps {
  children: ReactNode;
  className?: string;
  /** Entrance delay in seconds. */
  delay?: number;
}

// ─── <SlideIn direction="left|right|up|down" /> ───────────────
export interface SlideInProps extends BaseMotionProps {
  direction?: "left" | "right" | "up" | "down";
  /** Distance in pixels. Default 16. */
  distance?: number;
}

export function SlideIn({
  children,
  direction = "up",
  distance = 16,
  delay = 0,
  className,
}: SlideInProps) {
  const prefersReducedMotion = useReducedMotion();
  const offset =
    direction === "left"
      ? { x: -distance, y: 0 }
      : direction === "right"
        ? { x: distance, y: 0 }
        : direction === "down"
          ? { x: 0, y: -distance }
          : { x: 0, y: distance };

  return (
    <motion.div
      className={cn(className)}
      initial={prefersReducedMotion ? false : { opacity: 0, ...offset }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : { ...defaultTransition, delay }
      }
    >
      {children}
    </motion.div>
  );
}

// ─── <Stagger> / <StaggerItem> ────────────────────────────────
// Use: <Stagger><StaggerItem>A</StaggerItem><StaggerItem>B</StaggerItem></Stagger>
export interface StaggerProps extends BaseMotionProps {
  /** Time between children, in seconds. Default 0.06. */
  gap?: number;
  /** Tag to render — div by default. */
  as?: "div" | "ul" | "ol" | "section";
}

export function Stagger({
  children,
  gap,
  delay = 0,
  className,
  as = "div",
}: StaggerProps) {
  const prefersReducedMotion = useReducedMotion();
  const MotionTag =
    as === "ul"
      ? motion.ul
      : as === "ol"
        ? motion.ol
        : as === "section"
          ? motion.section
          : motion.div;

  const variants =
    gap !== undefined
      ? {
          hidden: {},
          visible: {
            transition: { staggerChildren: gap, delayChildren: delay },
          },
        }
      : delay
        ? {
            hidden: {},
            visible: {
              transition: { staggerChildren: 0.06, delayChildren: delay },
            },
          }
        : staggerParentVariants;

  return (
    <MotionTag
      className={cn(className)}
      variants={variants}
      initial={prefersReducedMotion ? "visible" : "hidden"}
      animate="visible"
    >
      {children}
    </MotionTag>
  );
}

export interface StaggerItemProps extends BaseMotionProps {
  variant?: "fade" | "fade-up" | "slide-left" | "slide-right";
  as?: "div" | "li";
}

export function StaggerItem({
  children,
  variant = "fade-up",
  className,
  as = "div",
}: StaggerItemProps) {
  const MotionTag = as === "li" ? motion.li : motion.div;
  const variants =
    variant === "fade"
      ? fadeVariants
      : variant === "slide-left"
        ? slideLeftVariants
        : variant === "slide-right"
          ? slideRightVariants
          : fadeUpVariants;
  return (
    <MotionTag className={cn(className)} variants={variants}>
      {children}
    </MotionTag>
  );
}

// ─── <ScrollReveal /> — trigger on enter viewport ─────────────
export interface ScrollRevealProps extends BaseMotionProps {
  /** Only animate once. Default true. */
  once?: boolean;
  /** How much of the element must be visible before triggering. Default 0.2. */
  amount?: number | "all" | "some";
  variant?: "fade" | "fade-up" | "slide-left" | "slide-right" | "scale-in";
}

export function ScrollReveal({
  children,
  delay = 0,
  once = true,
  amount = 0.2,
  variant = "fade-up",
  className,
}: ScrollRevealProps) {
  const prefersReducedMotion = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once, amount });

  const variants =
    variant === "fade"
      ? fadeVariants
      : variant === "slide-left"
        ? slideLeftVariants
        : variant === "slide-right"
          ? slideRightVariants
          : variant === "scale-in"
            ? scaleInVariants
            : fadeUpVariants;

  return (
    <motion.div
      ref={ref}
      className={cn(className)}
      variants={variants}
      initial={prefersReducedMotion ? "visible" : "hidden"}
      animate={prefersReducedMotion || inView ? "visible" : "hidden"}
      transition={
        prefersReducedMotion ? { duration: 0 } : { ...defaultTransition, delay }
      }
    >
      {children}
    </motion.div>
  );
}

// Re-export tokens for convenience.
export { MOTION };
