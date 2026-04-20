"use client";

import { startTransition, useEffect, useState } from "react";
import { X, Zap } from "lucide-react";
import { useStudio } from "./studio-context";

interface WarmupChallenge {
  label: string;
  description: string;
  starterCode: string;
}

const WARMUP_CHALLENGES: WarmupChallenge[] = [
  {
    label: "Reverse a string",
    description: "Write a function that reverses a string.",
    starterCode: `def reverse_string(s: str) -> str:
    # Your solution here
    pass

# Test it
print(reverse_string("hello"))   # Expected: "olleh"
print(reverse_string("Python"))  # Expected: "nohtyP"
`,
  },
  {
    label: "FizzBuzz one-liner",
    description: "Print FizzBuzz for 1–20 in a single line of code.",
    starterCode: `# FizzBuzz one-liner for numbers 1 to 20
# Print "Fizz" for multiples of 3, "Buzz" for multiples of 5,
# "FizzBuzz" for multiples of both, else the number.

# Your one-liner here:

`,
  },
  {
    label: "Count vowels",
    description: "Write a function that counts the number of vowels in a string.",
    starterCode: `def count_vowels(s: str) -> int:
    # Your solution here
    pass

# Test it
print(count_vowels("hello world"))  # Expected: 3
print(count_vowels("Python"))       # Expected: 1
`,
  },
  {
    label: "Check palindrome",
    description: "Write a function that checks if a string is a palindrome.",
    starterCode: `def is_palindrome(s: str) -> bool:
    # Your solution here (ignore case and spaces)
    pass

# Test it
print(is_palindrome("racecar"))   # Expected: True
print(is_palindrome("A man a plan a canal Panama"))  # Expected: True
print(is_palindrome("hello"))     # Expected: False
`,
  },
  {
    label: "Flatten a list",
    description: "Write a function that flattens a nested list one level deep.",
    starterCode: `def flatten(nested: list[list[int]]) -> list[int]:
    # Your solution here
    pass

# Test it
print(flatten([[1, 2], [3, 4], [5]]))  # Expected: [1, 2, 3, 4, 5]
print(flatten([[10], [], [20, 30]]))   # Expected: [10, 20, 30]
`,
  },
];

function todayKey(): string {
  const date = new Date().toISOString().slice(0, 10);
  return `studio-warmup-dismissed-${date}`;
}

function isDismissedToday(): boolean {
  try {
    return localStorage.getItem(todayKey()) === "1";
  } catch {
    return false;
  }
}

function dismissToday(): void {
  try {
    localStorage.setItem(todayKey(), "1");
  } catch {
    // quota exceeded — silent
  }
}

function pickChallenge(): WarmupChallenge {
  const index = new Date().getDate() % WARMUP_CHALLENGES.length;
  return WARMUP_CHALLENGES[index]!;
}

export function WarmupBanner() {
  const { code, hasRunOnce, setCode } = useStudio();
  const [visible, setVisible] = useState(false);
  const challenge = pickChallenge();

  useEffect(() => {
    // Only show when editor is empty and no run has happened yet
    const shouldShow = code === "" && !hasRunOnce && !isDismissedToday();
    startTransition(() => {
      setVisible(shouldShow);
    });
  }, [code, hasRunOnce]);

  if (!visible) return null;

  function handleLoad() {
    setCode(challenge.starterCode);
    setVisible(false);
  }

  function handleSkip() {
    dismissToday();
    setVisible(false);
  }

  return (
    <div
      role="note"
      aria-label="Daily warm-up challenge"
      className="flex items-center justify-between gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Zap className="h-4 w-4 shrink-0 text-amber-500" aria-hidden="true" />
        <p className="truncate text-amber-800 dark:text-amber-200">
          <span className="font-semibold">60-second warm-up:</span>{" "}
          {challenge.description}{" "}
          <span className="text-amber-600 dark:text-amber-400">Click to load →</span>
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={handleLoad}
          aria-label={`Load warm-up: ${challenge.label}`}
          className="rounded-md bg-amber-500 px-2.5 py-1 text-xs font-semibold text-white hover:bg-amber-600 transition"
        >
          Load challenge
        </button>
        <button
          type="button"
          onClick={handleSkip}
          aria-label="Dismiss warm-up challenge for today"
          className="rounded-md px-2 py-1 text-xs text-amber-700 hover:bg-amber-500/20 transition dark:text-amber-300"
        >
          Skip
        </button>
        <button
          type="button"
          onClick={handleSkip}
          aria-label="Close warm-up banner"
          className="rounded p-0.5 text-amber-700 hover:bg-amber-500/20 transition dark:text-amber-300"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
