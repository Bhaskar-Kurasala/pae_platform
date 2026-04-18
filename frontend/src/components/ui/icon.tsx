"use client";

import { forwardRef } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  BarChart3,
  Bell,
  BookOpen,
  Bot,
  Brain,
  Briefcase,
  BriefcaseBusiness,
  Calendar,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Circle,
  CircleCheck,
  Clock,
  Code2,
  Compass,
  Copy,
  Download,
  Ellipsis,
  ExternalLink,
  Eye,
  EyeOff,
  FileText,
  Filter,
  Flame,
  Gauge,
  GitBranch,
  GraduationCap,
  Heart,
  HelpCircle,
  Home,
  Info,
  Loader2,
  Lock,
  LogOut,
  Mail,
  Menu,
  MessageCircle,
  Minus,
  Moon,
  Pencil,
  PlayCircle,
  Plus,
  Radar,
  RefreshCw,
  Rocket,
  Search,
  Send,
  Settings,
  Share2,
  Shield,
  Sparkles,
  Star,
  Sun,
  Target,
  Trash2,
  TrendingDown,
  TrendingUp,
  Upload,
  User,
  Users,
  Wrench,
  X,
  Zap,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Semantic icon registry.
 *
 * Why a registry: lucide exports hundreds of icons. Letting every component
 * pick its own by free-text name leads to drift (Trash vs Trash2, Bot vs Cpu,
 * CheckCircle vs CheckCircle2). This registry fixes a single name → component
 * mapping for the whole app. Swap the backing icon here once; every callsite
 * updates.
 *
 * Rule of thumb: if the same concept appears in ≥2 places, it belongs here.
 */
export const ICON_REGISTRY = {
  // Navigation & chrome
  menu: Menu,
  close: X,
  back: ArrowLeft,
  home: Home,
  search: Search,
  filter: Filter,
  settings: Settings,
  logout: LogOut,
  more: Ellipsis,
  refresh: RefreshCw,

  // Chevrons (directional)
  "chevron-up": ChevronUp,
  "chevron-down": ChevronDown,
  "chevron-left": ChevronLeft,
  "chevron-right": ChevronRight,

  // Arrows (semantic actions)
  "arrow-up": ArrowUp,
  "arrow-down": ArrowDown,
  "arrow-left": ArrowLeft,
  "arrow-right": ArrowRight,
  "arrow-up-right": ArrowUpRight,
  send: Send,

  // Status / feedback
  check: Check,
  success: CheckCircle2,
  "check-circle": CircleCheck,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  help: HelpCircle,
  loading: Loader2,

  // Theme
  sun: Sun,
  moon: Moon,

  // Learning / content
  course: BookOpen,
  lesson: PlayCircle,
  exercise: Code2,
  progress: BarChart3,
  streak: Flame,
  dashboard: Home,
  chat: MessageCircle,
  today: Sun,

  // Goal / intent (onboarding)
  "intent-career": Briefcase,
  "intent-skill": Rocket,
  "intent-curiosity": Compass,
  "intent-interview": Target,
  goal: Target,

  // Signals (today page)
  "signal-job": BriefcaseBusiness,
  "signal-incident": AlertTriangle,
  "signal-shift": Radar,
  "signal-bench": Gauge,
  "signal-tool": Wrench,

  // CRUD / actions
  add: Plus,
  remove: Minus,
  edit: Pencil,
  delete: Trash2,
  copy: Copy,
  upload: Upload,
  download: Download,
  share: Share2,
  external: ExternalLink,
  link: GitBranch,

  // Visibility
  show: Eye,
  hide: EyeOff,
  lock: Lock,

  // People / identity
  user: User,
  users: Users,
  avatar: User,
  notification: Bell,
  email: Mail,

  // Brand moments / emphasis
  sparkles: Sparkles,
  magic: Sparkles,
  bolt: Zap,
  heart: Heart,
  star: Star,
  ai: Brain,
  agent: Bot,
  education: GraduationCap,
  shield: Shield,

  // Time / metrics
  calendar: Calendar,
  clock: Clock,
  "trend-up": TrendingUp,
  "trend-down": TrendingDown,

  // Documents
  file: FileText,

  // Generic shapes
  circle: Circle,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICON_REGISTRY;

const SIZE_MAP = {
  xs: 12,
  sm: 14,
  md: 16,
  lg: 20,
  xl: 24,
  "2xl": 32,
} as const;

export type IconSize = keyof typeof SIZE_MAP;

export interface IconProps extends Omit<LucideProps, "ref" | "size"> {
  name: IconName;
  size?: IconSize | number;
  /** When true, lucide's stroke is forced to 2.25 for better visibility on small sizes. */
  bold?: boolean;
  /** Decorative icons (no semantic meaning) should set aria-hidden. */
  decorative?: boolean;
}

/**
 * <Icon name="success" size="md" /> — canonical way to render an icon.
 *
 * For decorative icons, pass `decorative` (sets aria-hidden). For meaningful
 * icons (e.g. standalone button content), provide `aria-label`.
 */
export const Icon = forwardRef<SVGSVGElement, IconProps>(function Icon(
  {
    name,
    size = "md",
    bold = false,
    decorative = false,
    className,
    strokeWidth,
    ...props
  },
  ref,
) {
  const Component = ICON_REGISTRY[name];
  const resolvedSize = typeof size === "number" ? size : SIZE_MAP[size];
  const resolvedStroke =
    strokeWidth ?? (bold ? 2.25 : resolvedSize <= 14 ? 2 : 1.75);

  return (
    <Component
      ref={ref}
      size={resolvedSize}
      strokeWidth={resolvedStroke}
      aria-hidden={decorative ? true : undefined}
      className={cn("shrink-0", className)}
      {...props}
    />
  );
});
