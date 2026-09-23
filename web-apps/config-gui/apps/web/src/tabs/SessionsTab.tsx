import { DEFAULT_SCHEDULE, type Schedule } from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { TimeInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";

const SCHEDULE_FIELDS: Array<{
  key: "preOpen" | "openingAuction" | "continuous" | "closingAuction" | "closingEnd";
  label: string;
  /** CLI flag suffix, e.g. "pre-open" -> --pre-open / --weekend-pre-open / --holidays-pre-open. */
  flagSuffix: string;
}> = [
  { key: "preOpen", label: "Pre-open", flagSuffix: "pre-open" },
  { key: "openingAuction", label: "Opening auction", flagSuffix: "opening-auction" },
  { key: "continuous", label: "Continuous", flagSuffix: "continuous" },
  { key: "closingAuction", label: "Closing auction", flagSuffix: "closing-auction" },
  { key: "closingEnd", label: "Closing end", flagSuffix: "closing-end" },
];

const DEFAULT_BLOCK: Schedule = { ...DEFAULT_SCHEDULE };

/**
 * The schedule blocks the GUI exposes directly. Individual mon..sun
 * overrides are a hand-edit-the-YAML case (same call as config_gen's CLI
 * flags): the yaml-codec layer still parses and preserves them faithfully
 * on import/export, but there is no widget for them here.
 */
const BLOCKS: Array<{
  key: "weekdays" | "weekend" | "holidays";
  title: string;
  switchLabel: string;
  help: string;
  summaryLabel: string;
  /** CLI flag prefix for this block's five time flags (see SCHEDULE_FIELDS). */
  cliPrefix: string;
}> = [
  {
    key: "weekdays",
    title: "Weekdays",
    switchLabel: "Weekdays scheduled",
    help: "Applies Monday through Friday. Off means Mon-Fri are CLOSED all day.",
    summaryLabel: "Weekdays",
    cliPrefix: "",
  },
  {
    key: "weekend",
    title: "Weekend",
    switchLabel: "Weekend scheduled",
    help: "Applies to both Saturday and Sunday. Off (the default) means the weekend is CLOSED.",
    summaryLabel: "Weekend",
    cliPrefix: "weekend-",
  },
  {
    key: "holidays",
    title: "Holidays",
    switchLabel: "Holidays scheduled",
    help: "Applied instead of the weekday's own entry on a bank holiday for the configured country. Off (the default) means holidays are CLOSED.",
    summaryLabel: "Holidays",
    cliPrefix: "holidays-",
  },
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
            docHref: "../docs/user-guide/010-configuration.md",
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

        {canSee("I") && (
          <FieldRow
            label="Emit schedule block"
            path="emitSchedule"
            htmlFor="emit-schedule"
            help={{
              text: "Write an explicit schedule block. Turn off to let the scheduler use its own defaults (weekdays 09:00–16:05, weekend and holidays CLOSED). pm-scheduler reads the block whether or not sessions are enabled.",
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

      {draft.emitSchedule && !canSee("I") && (
        <Section
          title="Schedule"
          description="Times are HH:MM (24-hour) in server-local time and must be strictly increasing across the day."
        >
          <p className="text-sm text-fg-subtle">
            {BLOCKS.map(({ key, summaryLabel }) => {
              const block = draft.schedule[key];
              const summary = block
                ? SCHEDULE_FIELDS.map(({ key: fk }) => block[fk]).join(" · ")
                : "closed";
              return `${summaryLabel}: ${summary}`;
            }).join("  |  ")}
            .{" "}
            <span className="text-linked">Switch to Intermediate to customize session times.</span>
          </p>
        </Section>
      )}

      {draft.emitSchedule &&
        canSee("I") &&
        BLOCKS.map(({ key: blockKey, title, switchLabel, help, summaryLabel, cliPrefix }) => {
          const block = draft.schedule[blockKey];
          return (
            <Section
              key={blockKey}
              title={title}
              description={
                blockKey === "weekdays"
                  ? "Times are HH:MM (24-hour) in server-local time and must be strictly increasing across the day."
                  : undefined
              }
            >
              <FieldRow
                label={switchLabel}
                path={`schedule.${blockKey}`}
                htmlFor={`schedule-${blockKey}-enabled`}
                help={{ text: help }}
              >
                <Switch
                  id={`schedule-${blockKey}-enabled`}
                  aria-label={switchLabel}
                  checked={block !== undefined}
                  onCheckedChange={(checked) =>
                    update((d) => {
                      if (checked) {
                        d.schedule[blockKey] = { ...DEFAULT_BLOCK };
                      } else {
                        delete d.schedule[blockKey];
                      }
                    })
                  }
                />
              </FieldRow>

              {block &&
                SCHEDULE_FIELDS.map(({ key, label, flagSuffix }) => (
                  <FieldRow
                    key={key}
                    label={label}
                    path={`schedule.${blockKey}.${key}`}
                    help={{ text: `${label} time.`, cliFlag: `--${cliPrefix}${flagSuffix}` }}
                  >
                    <TimeInput
                      aria-label={`${summaryLabel} ${label}`}
                      value={block[key]}
                      onChange={(v) =>
                        update((d) => {
                          const b = d.schedule[blockKey];
                          if (b) b[key] = v;
                        })
                      }
                    />
                  </FieldRow>
                ))}
            </Section>
          );
        })}
    </Panel>
  );
}
