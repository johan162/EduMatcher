import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

/**
 * Flashes green or red for ~600ms when its value changes (design §15).
 *
 * The direction comes from comparing against the previous value, so the flash
 * says *which way* the price moved rather than merely that something happened.
 * A change to or from an absent value flashes neutrally: appearing liquidity
 * is not an uptick.
 */
export function FlashCell({
  value,
  children,
  className,
}: {
  value: number | undefined;
  children: React.ReactNode;
  className?: string;
}) {
  const previous = useRef<number | undefined>(value);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);

  useEffect(() => {
    const before = previous.current;
    previous.current = value;

    if (before === undefined || value === undefined || before === value) return;
    setFlash(value > before ? "up" : "down");

    // Clearing the class lets an immediately-following change retrigger the
    // animation; without it a fast series of ticks would flash only once.
    const timer = setTimeout(() => setFlash(null), 600);
    return () => clearTimeout(timer);
  }, [value]);

  return (
    <span
      data-flash={flash ?? undefined}
      className={clsx("tabular", flash === "up" && "flash-up", flash === "down" && "flash-down", className)}
    >
      {children}
    </span>
  );
}
