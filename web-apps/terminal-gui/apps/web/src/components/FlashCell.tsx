import clsx from "clsx";
import { useEffect, useRef, useState } from "react";

/**
 * Flashes green or red for ~600ms when its value changes (design §15).
 *
 * The direction comes from comparing against the previous value, so the flash
 * says *which way* the price moved rather than merely that something happened.
 * A change to or from an absent value flashes neutrally: appearing liquidity
 * is not an uptick.
 *
 * A caret rides alongside the colour (§ T-M3). Roughly one man in twelve has
 * a red-green deficiency, and this is the one place on the grid where
 * direction was carried by hue and nothing else — the change columns have
 * always had a leading `+`/`−`, but a flash on a bare price had no second
 * channel at all. The caret is absolutely positioned so adding it cannot
 * shift a column of tabular figures sideways every time one ticks.
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
      className={clsx(
        "relative tabular",
        flash === "up" && "flash-up",
        flash === "down" && "flash-down",
        className,
      )}
    >
      {flash && (
        <span
          aria-hidden
          className="absolute -left-2.5 top-0 text-[9px] leading-none"
          // Not aria-live: a screen reader announcing every tick on a grid
          // of fifty symbols would be unusable. The caret is a visual second
          // channel for the colour, and the price itself is already read.
        >
          {flash === "up" ? "▲" : "▼"}
        </span>
      )}
      {children}
    </span>
  );
}
