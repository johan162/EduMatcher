/**
 * Time to the next session transition (design §7.1, T-M6).
 *
 * The most-glanced item on a real trading screen, and the one this terminal
 * had no answer for: `STATE` carried the current phase and the previous one,
 * but nothing about what happens next or when. A trader watching a closing
 * auction approach was reading the wall clock and doing the arithmetic.
 *
 * Everything here treats "no transition scheduled" as a first-class state
 * rather than as zero. The feed genuinely does not always know: a manually
 * driven session, or one with no scheduler running, has no next transition
 * anybody can honestly name, and a screen that invented one would be lying
 * about the single thing this exists to tell.
 */

/** Below this, the transition is imminent enough to say so loudly. */
export const IMMINENT_SEC = 60;

export interface Countdown {
  /** Seconds remaining, floored at zero. */
  seconds: number;
  /** The phase being counted down to. */
  phase: string;
  /**
   * True once the scheduled moment has passed without the transition
   * arriving. The screen must not run a negative clock, but it must also not
   * silently show `0:00` forever — a scheduler that is late, wedged, or
   * simply not running all look like this, and the reader needs to know the
   * feed has stopped agreeing with its own timetable.
   */
  overdue: boolean;
  /** Within :data:`IMMINENT_SEC`, so worth emphasising. */
  imminent: boolean;
}

/**
 * Build the countdown, or `null` when there is nothing to count down to.
 *
 * `null` covers both "the feed named no transition" and "it named one this
 * client cannot read". An unparseable timestamp is not a reason to show a
 * wrong number.
 */
export function countdownTo(
  nextPhase: string | null | undefined,
  nextAt: string | null | undefined,
  now: number,
): Countdown | null {
  if (!nextPhase || !nextAt) return null;

  const target = Date.parse(nextAt);
  if (Number.isNaN(target)) return null;

  const remaining = Math.round((target - now) / 1000);
  return {
    seconds: Math.max(0, remaining),
    phase: nextPhase,
    overdue: remaining < 0,
    imminent: remaining >= 0 && remaining <= IMMINENT_SEC,
  };
}

/**
 * `1:04:22`, `4:22`, `22s` — coarsening downward, not upward.
 *
 * The opposite of the data-age formatter, and deliberately: an age is a
 * measurement that grows less interesting the larger it gets, while a
 * countdown grows *more* interesting the smaller it gets. Seconds matter at
 * the end of a call phase and hours matter at the start of the day, so this
 * keeps the seconds all the way down rather than rounding them away.
 */
export function formatCountdown(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  if (total < 60) return `${total}s`;

  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;

  const pad = (value: number): string => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

/** The whole strip reading, ready to render. */
export function countdownLabel(countdown: Countdown | null): string | null {
  if (countdown === null) return null;
  if (countdown.overdue) return `${countdown.phase} overdue`;
  return `${countdown.phase} in ${formatCountdown(countdown.seconds)}`;
}
