import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { TimeInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";

const SCHEDULE_FIELDS: Array<{
  key: "preOpen" | "openingAuction" | "continuous" | "closingAuction" | "closingEnd";
  label: string;
  flag: string;
}> = [
  { key: "preOpen", label: "Pre-open", flag: "--pre-open" },
  { key: "openingAuction", label: "Opening auction", flag: "--opening-auction" },
  { key: "continuous", label: "Continuous", flag: "--continuous" },
  { key: "closingAuction", label: "Closing auction", flag: "--closing-auction" },
  { key: "closingEnd", label: "Closing end", flag: "--closing-end" },
];

export function SessionsTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  return (
    <Panel
      tabId="sessions"
      title="Sessions & Schedule"
      intro="A trading day moves through phases: pre-open (stage orders), opening auction (uncross), continuous trading, then a closing auction. Enable sessions to let pm-scheduler drive these transitions."
    >
      <Section title="Session control">
        <FieldRow
          label="Sessions enabled"
          path="sessionsEnabled"
          htmlFor="sessions-enabled"
          help={{
            text: "When on, the engine starts CLOSED and pm-scheduler drives the trading-day timeline. When off, the engine runs in continuous mode and ignores the schedule.",
            cliFlag: "--sessions-enabled",
            docHref: "../docs/user-guide/01-configuration.md",
          }}
        >
          <Switch
            id="sessions-enabled"
            aria-label="Sessions enabled"
            checked={draft.sessionsEnabled}
            onCheckedChange={(checked) => update((d) => (d.sessionsEnabled = checked))}
          />
        </FieldRow>

        {draft.sessionsEnabled && (
          <div className="rounded-md border border-linked/40 bg-linked/10 px-3 py-2 text-sm text-fg-subtle">
            With sessions enabled you must run <code className="rounded bg-muted px-1">pm-scheduler</code>{" "}
            alongside the engine, or the market stays closed.
          </div>
        )}

        {draft.sessionsEnabled && canSee("I") && (
          <FieldRow
            label="Emit schedule block"
            path="emitSchedule"
            htmlFor="emit-schedule"
            help={{
              text: "Write an explicit schedule block. Turn off to let the scheduler use its own defaults.",
              cliFlag: "--schedule / --no-schedule",
            }}
          >
            <Switch
              id="emit-schedule"
              aria-label="Emit schedule block"
              checked={draft.emitSchedule}
              onCheckedChange={(checked) => update((d) => (d.emitSchedule = checked))}
            />
          </FieldRow>
        )}
      </Section>

      {draft.sessionsEnabled && (
        <Section
          title="Schedule"
          description="Times are HH:MM (24-hour) in server-local time and must be strictly increasing across the day."
        >
          {!canSee("I") ? (
            <p className="text-sm text-fg-subtle">
              Beginner mode emits the default schedule (09:00–16:05).{" "}
              <span className="text-linked">Switch to Intermediate to customize session times.</span>
            </p>
          ) : (
            SCHEDULE_FIELDS.map(({ key, label, flag }) => (
              <FieldRow
                key={key}
                label={label}
                path={`schedule.${key}`}
                help={{ text: `${label} time.`, cliFlag: flag }}
              >
                <TimeInput
                  aria-label={label}
                  value={draft.schedule[key]}
                  onChange={(v) => update((d) => (d.schedule[key] = v))}
                />
              </FieldRow>
            ))
          )}
        </Section>
      )}
    </Panel>
  );
}
