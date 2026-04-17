"use client";

import { type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

interface MotionFadeProps {
  children: ReactNode;
  /** Entrance delay in seconds. Default: 0. */
  delay?: number;
  className?: string;
}

/**
 * Reusable entrance animation wrapper using framer-motion.
 *
 * Animates: opacity 0→1, translateY 20px→0
 * Duration:  350ms, ease-out-quad [0.25, 0.46, 0.45, 0.94]
 * Respects:  prefers-reduced-motion — skips animation when user prefers it.
 *
 * Usage:
 *   <MotionFade delay={0.1}>
 *     <YourComponent />
 *   </MotionFade>
 */
export function MotionFade({ children, delay = 0, className }: MotionFadeProps) {
  const prefersReducedMotion = useReducedMotion();

  return (
    <motion.div
      className={cn(className)}
      initial={prefersReducedMotion ? false : { opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : {
              duration: 0.35,
              delay,
              ease: [0.25, 0.46, 0.45, 0.94],
            }
      }
    >
      {children}
    </motion.div>
  );
}
