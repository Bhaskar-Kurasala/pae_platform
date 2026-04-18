import type { Transition, Variants } from "framer-motion";

/**
 * Motion tokens — kept in sync with CSS custom properties in globals.css.
 * Use these in TS/JS motion configs so framer and CSS stay consistent.
 */
export const MOTION = {
  duration: {
    instant: 0,
    fast: 0.15,
    base: 0.25,
    slow: 0.4,
    slower: 0.6,
  },
  ease: {
    /** Primary app easing — matches globals.css --ease-out-quad */
    outQuad: [0.25, 0.46, 0.45, 0.94] as const,
    inOutQuad: [0.45, 0, 0.55, 1] as const,
    /** Overshoot spring for micro-interactions (toast in, badge pop). */
    spring: [0.34, 1.56, 0.64, 1] as const,
  },
} as const;

/** Default transition for most app animations. */
export const defaultTransition: Transition = {
  duration: MOTION.duration.base,
  ease: MOTION.ease.outQuad,
};

/** Transition for quick hover/tap feedback. */
export const fastTransition: Transition = {
  duration: MOTION.duration.fast,
  ease: MOTION.ease.outQuad,
};

/** Fade up 20px — the canonical entrance animation. */
export const fadeUpVariants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: defaultTransition },
};

/** Fade in place — subtler than fade-up, for in-layout elements. */
export const fadeVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: defaultTransition },
};

/** Slide from left. */
export const slideLeftVariants: Variants = {
  hidden: { opacity: 0, x: -16 },
  visible: { opacity: 1, x: 0, transition: defaultTransition },
};

/** Slide from right. */
export const slideRightVariants: Variants = {
  hidden: { opacity: 0, x: 16 },
  visible: { opacity: 1, x: 0, transition: defaultTransition },
};

/** Parent container that staggers its children. Use with child variants. */
export const staggerParentVariants: Variants = {
  hidden: {},
  visible: {
    transition: {
      staggerChildren: 0.06,
      delayChildren: 0.05,
    },
  },
};

/** Slight scale-in, useful for popovers/tooltips. */
export const scaleInVariants: Variants = {
  hidden: { opacity: 0, scale: 0.96 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: MOTION.duration.fast, ease: MOTION.ease.outQuad },
  },
};
