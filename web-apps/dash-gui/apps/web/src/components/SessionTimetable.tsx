/**
 * The Session schedule row's timetable (a copy of pm-terminal's Session view
 * panel; change them together): the week, the trading day as a flow of six
 * phases with the current one lit, the day to scale with a "now" marker, and
 * the next bank holiday.
 *
 *     MON 26  TUE 27  WED 28 ...                       ← this week
 *     Closed ─08:00▸ Pre-Open ─08:50▸ ... ▸ Closed     ← phase flow, NOW ringed
 *     ▒▒▒▒▒▒▒▒▓█████████████▓▒▒▒▒▒▒▒                   ← 00–24 with a needle
 *     Next bank holiday · Fri 25 Dec · Juldagen · Closed · in 61 days
 *
 * Phase colours are the session indicator's, so the top bar and this panel
 * name a phase the same way.
 */

import clsx from "clsx";
import { Fragment } from "react";
import type { ReferenceSchedule, SessionTimes } from "@edumatcher/dash-types";
import { phaseMeta } from "./SessionIndicator.js";
import { InfoTip } from "./shared/InfoTip.js";
import { timetableHelp } from "../lib/help.js";
import {
  DAY_SEC,
  PHASE_FLOW,
  boundaryLabels,
  clockLabel,
  currentStep,
  dateLabel,
  dayName,
  daySegments,
  daysBetween,
  exchangeNow,
  nextHoliday,
  nextTradingDay,
  segmentAt,
  weekOf,
} from "../lib/timetable.js";

const HOUR_TICKS = [0, 3, 6, 9, 12, 15, 18, 21, 24];

export interface SessionTimetableProps {
  /** Undefined while loading. */
  info: ReferenceSchedule | undefined;
  failed: boolean;
  phase: string | null;
  prev: string | null;
  timeZone: string;
  now: number;
}

export function SessionTimetable({ info, failed, phase, prev, timeZone, now }: SessionTimetableProps) {
  if (failed) return <Note>Timetable unavailable: pm-api-gwy is not reachable, or PM_DASH_API_KEY is not its read-only key.</Note>;
  if (!info) return null;
  if (!info.sessions_enabled)
    return <Note>Sessions are disabled: the exchange trades without a timetable.</Note>;
  const schedule = info.schedule;
  if (!schedule) return <Note>No session timetable is configured.</Note>;

  const today = exchangeNow(now, timeZone);
  const day = nextTradingDay(schedule, today.date);
  const holiday = nextHoliday(schedule, today.date);

  return (
    <div className="flex flex-col gap-4">
      <Week days={weekOf(schedule, today.date)} today={today.date} />
      {day ? (
        <Day
          times={day.times!}
          heading={
            day.date === today.date
              ? `Today${day.holiday ? ` · holiday hours (${day.holiday.name})` : ""}`
              : `Next trading day · ${dateLabel(day.date)}`
          }
          clockSec={day.date === today.date ? today.sec : null}
          phase={phase}
          prev={prev}
        />
      ) : (
        <Note>No trading day in the next two weeks.</Note>
      )}
      <div className="flex flex-wrap items-center gap-x-2 text-xs">
        <Heading label="Next bank holiday" />
        {holiday ? (
          <>
            <span className="font-semibold">{dateLabel(holiday.date)}</span>
            <Dot />
            <span className="text-fg-subtle">{holiday.holiday!.name}</span>
            <Dot />
            <span className={holiday.times ? "text-warning" : "text-error"}>
              {holiday.times ? `Holiday hours ${hours(holiday.times)}` : "Closed"}
            </span>
            <Dot />
            <span className="text-fg-faint">{inDays(daysBetween(today.date, holiday.date))}</span>
          </>
        ) : (
          <span className="text-fg-faint">None on a trading day in the coming year</span>
        )}
      </div>
    </div>
  );
}

function Week({ days, today }: { days: ReturnType<typeof weekOf>; today: string }) {
  return (
    <div>
      <Heading label="This week" />
      <ol className="mt-1 grid grid-cols-7 gap-1">
        {days.map((day) => {
          const isToday = day.date === today;
          return (
            <li
              key={day.date}
              aria-current={isToday ? "date" : undefined}
              title={day.holiday?.name}
              className={clsx(
                "min-w-0 rounded border px-1 py-1 text-center",
                day.times ? "border-border bg-bg-inset text-fg" : "border-dashed border-border text-fg-faint",
                isToday && "ring-2 ring-accent",
                day.date < today && "opacity-60",
              )}
            >
              <div className="text-[10px] uppercase tracking-widest">
                <span className={clsx(isToday && "font-bold text-accent")}>{dayName(day.dayKey)}</span>{" "}
                <span className="tabular">{Number(day.date.slice(8))}</span>
              </div>
              <div className="truncate text-xs tabular">{day.times ? hours(day.times) : "Closed"}</div>
              {day.holiday && <div className="truncate text-[10px] text-error">{day.holiday.name}</div>}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Day({
  times,
  heading,
  clockSec,
  phase,
  prev,
}: {
  times: SessionTimes;
  heading: string;
  /** The exchange's time of day when `times` is today's, else null. */
  clockSec: number | null;
  phase: string | null;
  prev: string | null;
}) {
  const segments = daySegments(times);
  if (!segments) return <Note>The timetable for this day cannot be read.</Note>;
  const labels = boundaryLabels(times);
  const clockStep = clockSec === null ? null : segmentAt(segments, clockSec);
  const current = currentStep(phase, prev, clockStep);
  // The needle claims "the exchange is here", so it shows only where the feed
  // agrees with the timetable.
  const onTimetable = clockStep !== null && current === clockStep;

  return (
    <div>
      <Heading label="Timetable" text={heading} />
      <ol aria-label="Session phases" className="mt-1 flex items-end gap-1 overflow-x-auto pb-1">
        {PHASE_FLOW.map((step, i) => (
          <Fragment key={i}>
            {i > 0 && (
              <li
                className="flex min-w-12 flex-1 flex-col items-center pb-1.5"
                aria-label={`then at ${labels[i - 1]}`}
              >
                <span className="font-mono text-[10px] text-fg-subtle">{labels[i - 1]}</span>
                <span className="flex w-full items-center text-fg-faint" aria-hidden="true">
                  <span className="h-px flex-1 bg-border-strong" />
                  <span className="text-[8px] leading-none">▶</span>
                </span>
              </li>
            )}
            <li
              aria-current={current === i ? "step" : undefined}
              className="flex shrink-0 flex-col items-center gap-1"
            >
              <span
                className={clsx(
                  "text-[9px] font-bold tracking-widest text-accent",
                  current !== i && "invisible",
                )}
              >
                NOW
              </span>
              <span
                className={clsx(
                  "whitespace-nowrap rounded",
                  current === i
                    ? `${phaseMeta(step).badge} px-3 py-1.5 text-sm font-semibold shadow-lg ring-2 ring-accent`
                    : "border border-border px-2 py-1 text-xs",
                  current !== i &&
                    (current !== null && clockStep !== null && i < current
                      ? "text-fg-faint"
                      : "text-fg-subtle"),
                )}
              >
                {phaseMeta(step).label}
              </span>
            </li>
          </Fragment>
        ))}
      </ol>

      <div className="relative mt-6" aria-hidden="true">
        {onTimetable && (
          <div
            data-testid="now-marker"
            className="absolute -top-5 z-10 flex -translate-x-1/2 flex-col items-center"
            style={{ left: `${(clockSec! / DAY_SEC) * 100}%` }}
          >
            <span className="font-mono text-[10px] text-fg">{hhmm(clockSec!)}</span>
            <span className="h-5 w-0.5 bg-fg" />
          </div>
        )}
        <div className="flex h-3 overflow-hidden rounded">
          {segments.map((s, i) => (
            <div
              key={i}
              title={`${phaseMeta(s.phase).label} ${hhmm(s.start)}–${hhmm(s.end)}`}
              style={{ width: `${((s.end - s.start) / DAY_SEC) * 100}%` }}
              className={clsx("min-w-[3px]", phaseMeta(s.phase).badge, i !== current && "opacity-25")}
            />
          ))}
        </div>
        <div className="relative mt-0.5 h-3 font-mono text-[9px] text-fg-faint">
          {HOUR_TICKS.map((h) => (
            <span
              key={h}
              className={clsx("absolute", h === 0 ? "" : h === 24 ? "-translate-x-full" : "-translate-x-1/2")}
              style={{ left: `${(h / 24) * 100}%` }}
            >
              {String(h).padStart(2, "0")}
            </span>
          ))}
        </div>
      </div>
      {clockStep !== null && current !== null && !onTimetable && (
        <p className="mt-1 text-[11px] text-fg-faint">
          The session is off its timetable right now (moved by an operator, or on a simulated clock), so no
          time marker is shown.
        </p>
      )}
    </div>
  );
}

function Heading({ label, text }: { label: string; text?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-widest text-fg-faint">
      {text ?? label}
      <InfoTip label={label} help={timetableHelp(label)!} />
    </span>
  );
}

function Dot() {
  return (
    <span className="text-fg-faint" aria-hidden="true">
      ·
    </span>
  );
}

function Note({ children }: { children: string }) {
  return <p className="text-xs text-fg-faint">{children}</p>;
}

/** Open to close, `08:00–17:30`. */
function hours(times: SessionTimes): string {
  return `${clockLabel(times.pre_open ?? "")}–${clockLabel(times.closing_auction_end ?? "")}`;
}

function hhmm(sec: number): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(sec / 3600))}:${pad(Math.floor((sec % 3600) / 60))}`;
}

function inDays(days: number): string {
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}
