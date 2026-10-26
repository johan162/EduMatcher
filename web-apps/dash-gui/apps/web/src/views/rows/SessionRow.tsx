/**
 * SESSION SCHEDULE: pm-terminal's session timetable -- the week, today's
 * phases with the current one lit, and the next bank holiday -- from
 * pm-api-gwy's /reference/schedule through the bridge, with the phase from
 * pm-md-gwy (the top bar's). The timetable changes only on a config reload,
 * so it is asked on each connect and every ten minutes.
 */

import { useEffect, useState } from "react";
import type { ReferenceSchedule } from "@edumatcher/dash-types";
import { phaseMeta } from "../../components/SessionIndicator.js";
import { SessionTimetable } from "../../components/SessionTimetable.js";
import { Row } from "../../components/widgets/Row.js";
import { getJson } from "../../lib/api.js";
import { useDashStore } from "../../store/useDashStore.js";

const SCHEDULE_POLL_MS = 10 * 60_000;
const CLOCK_MS = 10_000;

export function SessionRow() {
  const socket = useDashStore((s) => s.socket);
  const tz = useDashStore((s) => s.sessionTz);
  const phase = useDashStore((s) => s.session?.state ?? null);
  const [schedule, setSchedule] = useState<{ info?: ReferenceSchedule; failed: boolean }>({ failed: false });
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (socket !== "OPEN") return;
    const ctl = new AbortController();
    const load = () =>
      getJson<ReferenceSchedule>("/api/reference/schedule", ctl.signal).then(
        (info) => setSchedule({ info, failed: false }),
        () => !ctl.signal.aborted && setSchedule({ failed: true }),
      );
    void load();
    const timer = setInterval(load, SCHEDULE_POLL_MS);
    return () => {
      ctl.abort();
      clearInterval(timer);
    };
  }, [socket]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <Row
      id="session"
      title="Session schedule"
      badge={phase && phase !== "UNKNOWN" ? phaseMeta(phase).label : undefined}
    >
      {/* pm-md-gwy sends no previous phase; the clock tells the two CLOSED steps apart. */}
      <SessionTimetable
        info={schedule.info}
        failed={schedule.failed}
        phase={phase}
        prev={null}
        timeZone={tz}
        now={now}
      />
    </Row>
  );
}
