"use client";

import { useEffect, useState } from "react";
import { Check, Clock, X } from "lucide-react";
import { useStudio } from "./studio-context";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Difficulty = "warmup" | "intermediate" | "interview";

interface Challenge {
  id: string;
  title: string;
  difficulty: Difficulty;
  estimatedMinutes: number;
  description: string;
  starterCode: string;
}

// ---------------------------------------------------------------------------
// Challenge data
// ---------------------------------------------------------------------------

const CHALLENGES: Challenge[] = [
  // ── Warm-up ──────────────────────────────────────────────────────────────
  {
    id: "warmup-reverse-string",
    title: "Reverse a String",
    difficulty: "warmup",
    estimatedMinutes: 5,
    description: "Return the characters of a string in reversed order.",
    starterCode: `def reverse_string(s: str) -> str:
    """Return s reversed."""
    pass


# Test it
print(reverse_string("hello"))   # "olleh"
print(reverse_string("Python"))  # "nohtyP"
print(reverse_string(""))        # ""
`,
  },
  {
    id: "warmup-fizzbuzz",
    title: "FizzBuzz",
    difficulty: "warmup",
    estimatedMinutes: 5,
    description: "Print Fizz, Buzz, or FizzBuzz for numbers 1 to n.",
    starterCode: `def fizzbuzz(n: int) -> list[str]:
    """Return FizzBuzz list for 1..n.

    Multiples of 3 → "Fizz", multiples of 5 → "Buzz",
    multiples of both → "FizzBuzz", otherwise the number as a string.
    """
    pass


# Test it
print(fizzbuzz(15))
# ["1","2","Fizz","4","Buzz","Fizz","7","8","Fizz","Buzz","11","Fizz","13","14","FizzBuzz"]
`,
  },
  {
    id: "warmup-palindrome",
    title: "Palindrome Check",
    difficulty: "warmup",
    estimatedMinutes: 5,
    description: "Check whether a string reads the same forwards and backwards.",
    starterCode: `def is_palindrome(s: str) -> bool:
    """Return True if s is a palindrome (ignore case and spaces)."""
    pass


# Test it
print(is_palindrome("racecar"))                      # True
print(is_palindrome("A man a plan a canal Panama"))  # True
print(is_palindrome("hello"))                        # False
`,
  },
  {
    id: "warmup-count-vowels",
    title: "Count Vowels",
    difficulty: "warmup",
    estimatedMinutes: 5,
    description: "Count the number of vowels (a e i o u) in a string.",
    starterCode: `def count_vowels(s: str) -> int:
    """Return the number of vowels in s (case-insensitive)."""
    pass


# Test it
print(count_vowels("hello world"))  # 3
print(count_vowels("Python"))       # 1
print(count_vowels("aeiou"))        # 5
`,
  },
  {
    id: "warmup-flatten-list",
    title: "Flatten One Level",
    difficulty: "warmup",
    estimatedMinutes: 5,
    description: "Flatten a list of lists one level deep into a single list.",
    starterCode: `def flatten(nested: list[list[int]]) -> list[int]:
    """Return a flat list by concatenating each inner list."""
    pass


# Test it
print(flatten([[1, 2], [3, 4], [5]]))  # [1, 2, 3, 4, 5]
print(flatten([[10], [], [20, 30]]))   # [10, 20, 30]
print(flatten([]))                     # []
`,
  },

  // ── Intermediate ─────────────────────────────────────────────────────────
  {
    id: "intermediate-lru-cache",
    title: "Implement LRU Cache",
    difficulty: "intermediate",
    estimatedMinutes: 15,
    description: "Build a Least-Recently-Used cache with O(1) get and put.",
    starterCode: `class LRUCache:
    """Least-Recently-Used cache with fixed capacity.

    get(key)       → value or -1 if not present
    put(key, value) → insert/update; evict LRU entry when over capacity
    Both operations must run in O(1) time.
    """

    def __init__(self, capacity: int) -> None:
        pass

    def get(self, key: int) -> int:
        pass

    def put(self, key: int, value: int) -> None:
        pass


# Test it
cache = LRUCache(2)
cache.put(1, 1)
cache.put(2, 2)
print(cache.get(1))   # 1
cache.put(3, 3)       # evicts key 2
print(cache.get(2))   # -1 (evicted)
print(cache.get(3))   # 3
`,
  },
  {
    id: "intermediate-merge-sorted",
    title: "Merge Two Sorted Lists",
    difficulty: "intermediate",
    estimatedMinutes: 15,
    description: "Merge two sorted lists into one sorted list in O(n+m).",
    starterCode: `def merge_sorted(a: list[int], b: list[int]) -> list[int]:
    """Return a single sorted list containing all elements of a and b."""
    pass


# Test it
print(merge_sorted([1, 3, 5], [2, 4, 6]))   # [1, 2, 3, 4, 5, 6]
print(merge_sorted([], [1, 2]))              # [1, 2]
print(merge_sorted([5], [1, 2, 3, 4]))      # [1, 2, 3, 4, 5]
`,
  },
  {
    id: "intermediate-group-anagrams",
    title: "Group Anagrams",
    difficulty: "intermediate",
    estimatedMinutes: 15,
    description: "Group a list of strings into sublists of anagrams.",
    starterCode: `def group_anagrams(words: list[str]) -> list[list[str]]:
    """Group words that are anagrams of each other.

    The order of groups and words within groups does not matter.
    """
    pass


# Test it
result = group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"])
# Expected (any order): [["eat","tea","ate"], ["tan","nat"], ["bat"]]
for group in sorted(result, key=lambda g: sorted(g)):
    print(sorted(group))
`,
  },
  {
    id: "intermediate-binary-search",
    title: "Binary Search",
    difficulty: "intermediate",
    estimatedMinutes: 15,
    description: "Find a target value in a sorted array in O(log n).",
    starterCode: `def binary_search(nums: list[int], target: int) -> int:
    """Return the index of target in the sorted list, or -1 if not found."""
    pass


# Test it
print(binary_search([1, 3, 5, 7, 9, 11], 7))   # 3
print(binary_search([1, 3, 5, 7, 9, 11], 6))   # -1
print(binary_search([], 1))                      # -1
print(binary_search([42], 42))                   # 0
`,
  },
  {
    id: "intermediate-valid-parens",
    title: "Valid Parentheses",
    difficulty: "intermediate",
    estimatedMinutes: 15,
    description: "Check whether brackets in a string are properly matched.",
    starterCode: `def is_valid(s: str) -> bool:
    """Return True if s has balanced brackets: (), [], {}.

    Every opening bracket must be closed by the same type in the
    correct order.
    """
    pass


# Test it
print(is_valid("()[]{}"))    # True
print(is_valid("([{}])"))    # True
print(is_valid("(]"))        # False
print(is_valid("([)]"))      # False
print(is_valid("{[]"))       # False
`,
  },

  // ── Interview ─────────────────────────────────────────────────────────────
  {
    id: "interview-longest-substring",
    title: "Longest Substring Without Repeats",
    difficulty: "interview",
    estimatedMinutes: 30,
    description: "Find the length of the longest substring with all unique chars.",
    starterCode: `def length_of_longest_substring(s: str) -> int:
    """Return the length of the longest substring without repeating characters.

    Aim for O(n) time using a sliding window.
    """
    pass


# Test it
print(length_of_longest_substring("abcabcbb"))  # 3  ("abc")
print(length_of_longest_substring("bbbbb"))     # 1  ("b")
print(length_of_longest_substring("pwwkew"))    # 3  ("wke")
print(length_of_longest_substring(""))          # 0
`,
  },
  {
    id: "interview-word-frequency-streaming",
    title: "Word Frequency with Streaming",
    difficulty: "interview",
    estimatedMinutes: 30,
    description: "Count word frequencies from a large text stream chunk-by-chunk.",
    starterCode: `from collections import Counter
from typing import Iterator


def stream_word_frequency(chunks: Iterator[str]) -> dict[str, int]:
    """Count word frequencies by processing an iterator of text chunks.

    Each chunk may be split mid-word at its boundary — handle that correctly.
    Words are lowercased and stripped of punctuation for counting.
    """
    pass


# Test it
import re

def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())

chunks = iter(["the quick br", "own fox jum", "ps over the lazy dog"])
freq = stream_word_frequency(chunks)
print(sorted(freq.items()))
# [('brown', 1), ('dog', 1), ('fox', 1), ('jumps', 1),
#  ('lazy', 1), ('over', 1), ('quick', 1), ('the', 2)]
`,
  },
  {
    id: "interview-rate-limiter",
    title: "Implement a Rate Limiter",
    difficulty: "interview",
    estimatedMinutes: 30,
    description: "Token-bucket rate limiter: allow N requests per window.",
    starterCode: `import time


class RateLimiter:
    """Token-bucket rate limiter.

    allow(user_id) → True if the user is within their rate limit,
                     False otherwise.

    Each user gets 'max_requests' tokens per 'window_seconds' window.
    Use a sliding-window or fixed-window strategy — justify your choice.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        pass

    def allow(self, user_id: str) -> bool:
        pass


# Test it
limiter = RateLimiter(max_requests=3, window_seconds=1.0)
user = "alice"
print(limiter.allow(user))  # True
print(limiter.allow(user))  # True
print(limiter.allow(user))  # True
print(limiter.allow(user))  # False — limit hit
time.sleep(1.1)
print(limiter.allow(user))  # True — window reset
`,
  },
  {
    id: "interview-circuit-breaker",
    title: "Design a Circuit Breaker",
    difficulty: "interview",
    estimatedMinutes: 30,
    description: "Protect downstream calls with open/half-open/closed states.",
    starterCode: `import time
from enum import Enum, auto


class State(Enum):
    CLOSED = auto()     # Normal — requests pass through
    OPEN = auto()       # Tripped — requests fail fast
    HALF_OPEN = auto()  # Probe — one request allowed to test recovery


class CircuitBreaker:
    """Three-state circuit breaker.

    call(fn) → executes fn() if CLOSED or HALF_OPEN.
                - On success in HALF_OPEN → transition to CLOSED
                - On failure in HALF_OPEN → back to OPEN
                - When failures ≥ failure_threshold → OPEN
                - After reset_timeout seconds in OPEN → HALF_OPEN
    Raises RuntimeError immediately when OPEN.
    """

    def __init__(self, failure_threshold: int, reset_timeout: float) -> None:
        pass

    def call(self, fn: "Callable[[], object]") -> object:
        pass


from typing import Callable

# Test it
import random

breaker = CircuitBreaker(failure_threshold=3, reset_timeout=2.0)

def flaky() -> str:
    if random.random() < 0.7:
        raise ConnectionError("service down")
    return "ok"

for i in range(8):
    try:
        result = breaker.call(flaky)
        print(f"call {i}: {result} | state={breaker.state.name}")
    except Exception as e:
        print(f"call {i}: ERROR {e} | state={breaker.state.name}")
`,
  },
  {
    id: "interview-retry-decorator",
    title: "Retry Decorator with Exponential Backoff",
    difficulty: "interview",
    estimatedMinutes: 30,
    description: "Write a decorator that retries a function with exponential backoff.",
    starterCode: `import time
import functools
from typing import Callable, TypeVar, ParamSpec

P = ParamSpec("P")
R = TypeVar("R")


def retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator: retry the wrapped function on specified exceptions.

    Delay between attempts: base_delay * (backoff_factor ** attempt_index)
    Raises the last exception if all attempts are exhausted.
    """
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            pass
        return wrapper
    return decorator


# Test it
attempt_count = 0

@retry(max_attempts=4, base_delay=0.05, backoff_factor=2.0,
       exceptions=(ValueError,))
def unstable(threshold: int) -> str:
    global attempt_count
    attempt_count += 1
    if attempt_count < threshold:
        raise ValueError(f"not ready (attempt {attempt_count})")
    return f"success on attempt {attempt_count}"

attempt_count = 0
print(unstable(3))   # "success on attempt 3"
`,
  },
];

// ---------------------------------------------------------------------------
// LocalStorage helpers
// ---------------------------------------------------------------------------

const DONE_KEY = "studio-challenges-done";

function loadDone(): string[] {
  try {
    const raw = localStorage.getItem(DONE_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function saveDone(ids: string[]): void {
  try {
    localStorage.setItem(DONE_KEY, JSON.stringify(ids));
  } catch {
    // quota exceeded — silent
  }
}

// ---------------------------------------------------------------------------
// Difficulty config
// ---------------------------------------------------------------------------

interface DifficultyMeta {
  label: string;
  minutes: string;
  tabActive: string;
  tabInactive: string;
  badge: string;
  timeBadge: string;
  border: string;
  progressBar: string;
}

const DIFFICULTY_META: Record<Difficulty, DifficultyMeta> = {
  warmup: {
    label: "Warm-up",
    minutes: "5 min",
    tabActive: "bg-emerald-500 text-white",
    tabInactive: "text-emerald-700 hover:bg-emerald-50 dark:text-emerald-400 dark:hover:bg-emerald-950/40",
    badge: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30",
    timeBadge: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
    border: "hover:border-emerald-400/50",
    progressBar: "bg-emerald-500",
  },
  intermediate: {
    label: "Intermediate",
    minutes: "15 min",
    tabActive: "bg-amber-500 text-white",
    tabInactive: "text-amber-700 hover:bg-amber-50 dark:text-amber-400 dark:hover:bg-amber-950/40",
    badge: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30",
    timeBadge: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
    border: "hover:border-amber-400/50",
    progressBar: "bg-amber-500",
  },
  interview: {
    label: "Interview",
    minutes: "30 min",
    tabActive: "bg-red-500 text-white",
    tabInactive: "text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40",
    badge: "bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/30",
    timeBadge: "bg-red-500/10 text-red-700 dark:text-red-400",
    border: "hover:border-red-400/50",
    progressBar: "bg-red-500",
  },
};

const DIFFICULTY_ORDER: Difficulty[] = ["warmup", "intermediate", "interview"];
const TOTAL_CHALLENGES = CHALLENGES.length; // 15

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ChallengeCard({
  challenge,
  done,
  onSelect,
}: {
  challenge: Challenge;
  done: boolean;
  onSelect: () => void;
}) {
  const meta = DIFFICULTY_META[challenge.difficulty];
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={`Load challenge: ${challenge.title}`}
      className={`group w-full rounded-lg border border-border bg-card p-3 text-left transition ${meta.border} hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="flex-1 text-sm font-medium leading-snug text-foreground group-hover:text-primary">
          {challenge.title}
        </span>
        {done ? (
          <span
            aria-label="Completed"
            className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
          >
            <Check className="h-3 w-3" aria-hidden="true" />
          </span>
        ) : (
          <span
            className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${meta.timeBadge} inline-flex items-center gap-0.5`}
          >
            <Clock className="h-2.5 w-2.5" aria-hidden="true" />
            {challenge.estimatedMinutes} min
          </span>
        )}
      </div>
      <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
        {challenge.description}
      </p>
    </button>
  );
}

// ---------------------------------------------------------------------------
// ChallengePicker
// ---------------------------------------------------------------------------

export function ChallengePicker({ onClose }: { onClose: () => void }) {
  const { setCode } = useStudio();
  const [activeTab, setActiveTab] = useState<Difficulty>("warmup");
  const [done, setDone] = useState<string[]>([]);

  // Hydrate from localStorage on mount (client-only)
  useEffect(() => {
    setDone(loadDone());
  }, []);

  const visibleChallenges = CHALLENGES.filter((c) => c.difficulty === activeTab);
  const doneCount = done.length;

  function handleSelect(challenge: Challenge) {
    setCode(challenge.starterCode);
    // Mark as done (or at least "started" — good enough for progress)
    const updated = done.includes(challenge.id) ? done : [...done, challenge.id];
    setDone(updated);
    saveDone(updated);
    onClose();
  }

  const progressPct = Math.round((doneCount / TOTAL_CHALLENGES) * 100);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
            Challenges
          </p>
          <h2 className="text-sm font-semibold text-foreground">Challenge Ladder</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close challenge picker"
          className="rounded-md p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {/* Progress */}
      <div className="border-b border-border px-4 py-2.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Progress</span>
          <span className="font-medium text-foreground">
            {doneCount}/{TOTAL_CHALLENGES} challenges complete
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={doneCount}
          aria-valuemin={0}
          aria-valuemax={TOTAL_CHALLENGES}
          aria-label={`${doneCount} of ${TOTAL_CHALLENGES} challenges complete`}
          className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted"
        >
          <div
            className="h-full rounded-full bg-primary transition-all duration-300"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Difficulty tabs */}
      <div
        role="tablist"
        aria-label="Difficulty"
        className="flex gap-1 border-b border-border px-3 py-2"
      >
        {DIFFICULTY_ORDER.map((diff) => {
          const meta = DIFFICULTY_META[diff];
          const isActive = activeTab === diff;
          return (
            <button
              key={diff}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-label={`${meta.label} challenges`}
              onClick={() => setActiveTab(diff)}
              className={`flex-1 rounded-md px-2 py-1.5 text-xs font-semibold transition ${
                isActive ? meta.tabActive : meta.tabInactive
              }`}
            >
              {meta.label}
            </button>
          );
        })}
      </div>

      {/* Tier badge */}
      <div className="px-4 pt-3 pb-1">
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${DIFFICULTY_META[activeTab].badge}`}
        >
          <Clock className="h-3 w-3" aria-hidden="true" />
          {DIFFICULTY_META[activeTab].minutes} each
        </span>
      </div>

      {/* Challenge list */}
      <div
        role="tabpanel"
        aria-label={`${DIFFICULTY_META[activeTab].label} challenges`}
        className="flex-1 overflow-y-auto px-3 pb-4"
      >
        <div className="mt-2 flex flex-col gap-2">
          {visibleChallenges.map((challenge) => (
            <ChallengeCard
              key={challenge.id}
              challenge={challenge}
              done={done.includes(challenge.id)}
              onSelect={() => handleSelect(challenge)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ChallengeDrawer — full overlay wrapper used by studio/page.tsx
// ---------------------------------------------------------------------------

export function ChallengeDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  // Keyboard: close on Escape
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden="true"
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Challenge picker"
        className="fixed inset-y-0 left-0 z-50 w-80 border-r border-border bg-background shadow-xl"
      >
        <ChallengePicker onClose={onClose} />
      </aside>
    </>
  );
}
