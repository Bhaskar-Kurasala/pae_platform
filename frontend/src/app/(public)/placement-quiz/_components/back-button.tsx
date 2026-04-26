"use client";

interface BackButtonProps {
  onClick: () => void;
}

export function BackButton({ onClick }: BackButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Go back to previous question"
      className="inline-flex items-center gap-1 text-xs text-[#a29a8a] hover:text-[#f0ece1] focus:text-[#f0ece1] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#5db288] focus-visible:ring-offset-2 focus-visible:ring-offset-[#10120e] rounded transition-colors"
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 14 14"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M9 11L4 7l5-4" />
      </svg>
      Back
    </button>
  );
}
