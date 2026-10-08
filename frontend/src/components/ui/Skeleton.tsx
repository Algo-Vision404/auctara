import clsx from "clsx";

/**
 * Loading placeholder for a value that is still in flight. Distinct from
 * "N/A" (a value the backend genuinely returned as absent): a skeleton
 * means "a real number is coming," N/A means "there is no number here."
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={clsx("inline-block animate-pulse rounded-md bg-[var(--color-surface-2)]", className)}
    />
  );
}
