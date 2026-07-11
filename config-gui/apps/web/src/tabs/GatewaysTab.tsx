import * as Tabs from "@radix-ui/react-tabs";
import {
  API_LOG_LEVELS,
  DUPLICATE_SESSION_POLICIES,
  POST_TRADE_ROLES,
  createApiGateway,
  type ApiLogLevel,
  type DuplicateSessionPolicy,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { Panel } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { Switch } from "@/components/ui/Switch";

const TAB_TRIGGER =
  "rounded-t px-3 py-1.5 text-sm data-[state=active]:border-b-2 data-[state=active]:border-accent data-[state=active]:font-medium";

export function GatewaysTab() {
  const { canSee } = usePersona();

  return (
    <Panel
      tabId="gateways"
      title="Auxiliary Gateways"
      intro="Optional network services around the engine: post-trade (fills/drop-copy), market-data (snapshots), BALF (binary access), and the REST/WebSocket API gateway. Enable only what your scenario needs. Ports are collision-checked across all gateways."
    >
      <Tabs.Root defaultValue="post-trade" className="mt-2">
        <Tabs.List className="mb-4 flex flex-wrap gap-1 border-b border-border">
          <Tabs.Trigger value="post-trade" className={TAB_TRIGGER}>Post-Trade</Tabs.Trigger>
          <Tabs.Trigger value="market-data" className={TAB_TRIGGER}>Market-Data</Tabs.Trigger>
          {canSee("E") && <Tabs.Trigger value="balf" className={TAB_TRIGGER}>BALF</Tabs.Trigger>}
          {canSee("E") && <Tabs.Trigger value="api" className={TAB_TRIGGER}>API</Tabs.Trigger>}
        </Tabs.List>

        <Tabs.Content value="post-trade"><PostTradePanel /></Tabs.Content>
        <Tabs.Content value="market-data"><MarketDataPanel /></Tabs.Content>
        {canSee("E") && <Tabs.Content value="balf"><BalfPanel /></Tabs.Content>}
        {canSee("E") && <Tabs.Content value="api"><ApiPanel /></Tabs.Content>}
      </Tabs.Root>
    </Panel>
  );
}

function PostTradePanel() {
  const g = useDraftStore((s) => s.draft.postTradeGateway);
  const update = useDraftStore((s) => s.update);
  const set = (fn: (gw: typeof g) => void) => update((d) => fn(d.postTradeGateway));

  return (
    <div>
      <EnableRow enabled={g.enabled} onToggle={(v) => set((gw) => (gw.enabled = v))} label="Enable post-trade gateway" flag="--post-trade-gateway" />
      {g.enabled && (
        <>
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} />
          <NumField label="Port" path="postTradeGateway.port" value={g.port} onChange={(v) => set((gw) => (gw.port = v ?? gw.port))} />
          <NumField label="Replay retention (sec)" value={g.replayRetentionSec} onChange={(v) => set((gw) => (gw.replayRetentionSec = v ?? gw.replayRetentionSec))} />
          <NumField label="Heartbeat interval (sec)" value={g.heartbeatIntervalSec} onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))} />
          <NumField label="Idle timeout (sec)" value={g.idleTimeoutSec} onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))} />
          <NumField label="Max client queue" value={g.maxClientQueue} onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))} />
          <FieldRow label="Allowed roles">
            <div className="flex flex-wrap gap-1.5">
              {POST_TRADE_ROLES.map((role) => {
                const on = g.allowedRoles.includes(role);
                return (
                  <button
                    key={role}
                    type="button"
                    onClick={() => set((gw) => (gw.allowedRoles = on ? gw.allowedRoles.filter((r) => r !== role) : [...gw.allowedRoles, role]))}
                    className={on ? "rounded-full border border-accent bg-accent px-2.5 py-0.5 text-sm text-accent-fg" : "rounded-full border border-border px-2.5 py-0.5 text-sm hover:bg-muted"}
                  >
                    {role}
                  </button>
                );
              })}
            </div>
          </FieldRow>
        </>
      )}
    </div>
  );
}

function MarketDataPanel() {
  const g = useDraftStore((s) => s.draft.marketDataGateway);
  const update = useDraftStore((s) => s.update);
  const set = (fn: (gw: typeof g) => void) => update((d) => fn(d.marketDataGateway));

  return (
    <div>
      <EnableRow enabled={g.enabled} onToggle={(v) => set((gw) => (gw.enabled = v))} label="Enable market-data gateway" flag="--market-data-gateway" />
      {g.enabled && (
        <>
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} />
          <NumField label="Port" path="marketDataGateway.port" value={g.port} onChange={(v) => set((gw) => (gw.port = v ?? gw.port))} />
          <NumField label="Heartbeat interval (sec)" value={g.heartbeatIntervalSec} onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))} />
          <NumField label="Idle timeout (sec)" value={g.idleTimeoutSec} onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))} />
          <NumField label="Replay window (sec)" value={g.replayWindowSec} onChange={(v) => set((gw) => (gw.replayWindowSec = v ?? gw.replayWindowSec))} />
          <NumField label="Max symbols per client" value={g.maxSymbolsPerClient} onChange={(v) => set((gw) => (gw.maxSymbolsPerClient = v ?? gw.maxSymbolsPerClient))} />
          <NumField label="Max client queue" value={g.maxClientQueue} onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))} />
          <NumField label="Depth levels" value={g.depthLevels} onChange={(v) => set((gw) => (gw.depthLevels = v ?? gw.depthLevels))} />
        </>
      )}
    </div>
  );
}

function BalfPanel() {
  const g = useDraftStore((s) => s.draft.balfGateway);
  const update = useDraftStore((s) => s.update);
  const set = (fn: (gw: typeof g) => void) => update((d) => fn(d.balfGateway));

  return (
    <div>
      <EnableRow enabled={g.enabled} onToggle={(v) => set((gw) => (gw.enabled = v))} label="Enable BALF gateway" flag="--balf-gateway" />
      {g.enabled && (
        <>
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} />
          <NumField label="Port" path="balfGateway.port" value={g.port} onChange={(v) => set((gw) => (gw.port = v ?? gw.port))} />
          <NumField label="Heartbeat interval (sec)" value={g.heartbeatIntervalSec} onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))} />
          <NumField label="Heartbeat timeout (sec)" value={g.heartbeatTimeoutSec} onChange={(v) => set((gw) => (gw.heartbeatTimeoutSec = v ?? gw.heartbeatTimeoutSec))} />
          <NumField label="Idle timeout (sec)" value={g.idleTimeoutSec} onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))} />
          <NumField label="Auth timeout (sec)" value={g.authTimeoutSec} onChange={(v) => set((gw) => (gw.authTimeoutSec = v ?? gw.authTimeoutSec))} />
          <NumField label="Max connections" value={g.maxConnections} onChange={(v) => set((gw) => (gw.maxConnections = v ?? gw.maxConnections))} />
          <NumField label="Max client queue" value={g.maxClientQueue} onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))} />
          <NumField label="Max messages/sec" value={g.maxMessagesPerSecond} onChange={(v) => set((gw) => (gw.maxMessagesPerSecond = v ?? gw.maxMessagesPerSecond))} />
          <NumField label="Max errors before disconnect" value={g.maxErrorsBeforeDisconnect} onChange={(v) => set((gw) => (gw.maxErrorsBeforeDisconnect = v ?? gw.maxErrorsBeforeDisconnect))} />
          <NumField label="Error window (sec)" value={g.errorWindowSec} onChange={(v) => set((gw) => (gw.errorWindowSec = v ?? gw.errorWindowSec))} />
          <FieldRow label="Duplicate session policy">
            <Select
              aria-label="Duplicate session policy"
              value={g.duplicateSessionPolicy}
              onValueChange={(v) => set((gw) => (gw.duplicateSessionPolicy = v as DuplicateSessionPolicy))}
              options={DUPLICATE_SESSION_POLICIES.map((p) => ({ value: p, label: p }))}
            />
          </FieldRow>
        </>
      )}
    </div>
  );
}

function ApiPanel() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const gateways = draft.apiGateways;

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-fg-subtle">
          REST/WebSocket API gateway instances. Multiple instances can each be scoped to a subset of ALF gateway IDs.
        </p>
        <button
          type="button"
          onClick={() =>
            update((d) => {
              let i = d.apiGateways.length + 1;
              let name = i === 1 ? "default" : `api${i}`;
              while (d.apiGateways.some((g) => g.name === name)) name = `api${++i}`;
              d.apiGateways.push(createApiGateway(name));
            })
          }
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          + Add instance
        </button>
      </div>

      {gateways.length === 0 && <p className="text-sm text-fg-subtle">No API gateway configured.</p>}

      {gateways.map((gw, i) => (
        <div key={i} className="mt-3 rounded-md border border-border bg-surface p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium">{gw.name}</h3>
            <button
              type="button"
              onClick={() => update((d) => d.apiGateways.splice(i, 1))}
              className="text-sm text-fg-subtle hover:text-error"
            >
              Remove
            </button>
          </div>

          <TextField label="Instance name" value={gw.name} onChange={(v) => update((d) => (d.apiGateways[i]!.name = v))} />
          <TextField label="Host" value={gw.host} onChange={(v) => update((d) => (d.apiGateways[i]!.host = v))} />
          <NumField label="Port" path={`apiGateways.${gw.name}.port`} value={gw.port} onChange={(v) => update((d) => (d.apiGateways[i]!.port = v ?? gw.port))} />

          <FieldRow label="Scoped gateway IDs" path={`apiGateways.${gw.name}.gatewayIds`} help={{ text: "ALF gateway IDs this instance serves. Leave empty to serve all. Each ID may belong to only one instance.", cliFlag: "--api-gateway-instance" }}>
            <div className="flex flex-wrap gap-1.5">
              {draft.gateways.length === 0 && <span className="text-sm text-fg-subtle">Add ALF gateways in Basics.</span>}
              {draft.gateways.map((alf) => {
                const on = gw.gatewayIds.includes(alf.id);
                return (
                  <button
                    key={alf.id}
                    type="button"
                    onClick={() =>
                      update((d) => {
                        const ids = d.apiGateways[i]!.gatewayIds;
                        d.apiGateways[i]!.gatewayIds = on ? ids.filter((x) => x !== alf.id) : [...ids, alf.id];
                      })
                    }
                    className={on ? "rounded-full border border-accent bg-accent px-2.5 py-0.5 text-sm text-accent-fg" : "rounded-full border border-border px-2.5 py-0.5 text-sm hover:bg-muted"}
                  >
                    {alf.id}
                  </button>
                );
              })}
            </div>
          </FieldRow>

          <FieldRow label="Swagger UI">
            <Switch aria-label="Swagger UI enabled" checked={gw.swaggerEnabled} onCheckedChange={(v) => update((d) => (d.apiGateways[i]!.swaggerEnabled = v))} />
          </FieldRow>
          <FieldRow label="Log level">
            <Select
              aria-label="Log level"
              value={gw.logLevel}
              onValueChange={(v) => update((d) => (d.apiGateways[i]!.logLevel = v as ApiLogLevel))}
              options={API_LOG_LEVELS.map((l) => ({ value: l, label: l }))}
            />
          </FieldRow>
          <TextField label="Stats DB path" value={gw.statsDb} onChange={(v) => update((d) => (d.apiGateways[i]!.statsDb = v))} />
          <div className="flex flex-wrap gap-4">
            <NumField label="Rate limit writes/sec" value={gw.rateLimitWritesPerSecond} onChange={(v) => update((d) => (d.apiGateways[i]!.rateLimitWritesPerSecond = v ?? gw.rateLimitWritesPerSecond))} />
            <NumField label="Rate limit burst" value={gw.rateLimitBurst} onChange={(v) => update((d) => (d.apiGateways[i]!.rateLimitBurst = v ?? gw.rateLimitBurst))} />
          </div>
          <FieldRow label="Auto-generate keys" help={{ text: "Generate a per-gateway API key for each ALF gateway on export.", cliFlag: "--api-gateway-generate-keys" }}>
            <Switch aria-label="Auto-generate keys" checked={gw.generateKeys} onCheckedChange={(v) => update((d) => (d.apiGateways[i]!.generateKeys = v))} />
          </FieldRow>
        </div>
      ))}
    </div>
  );
}

// --- small shared field helpers for the gateway panels ----------------------

function EnableRow({ enabled, onToggle, label, flag }: { enabled: boolean; onToggle: (v: boolean) => void; label: string; flag: string }) {
  return (
    <FieldRow label={label} help={{ text: "Turning this off keeps your values but excludes the section from the exported config.", cliFlag: flag }}>
      <Switch aria-label={label} checked={enabled} onCheckedChange={onToggle} />
    </FieldRow>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <FieldRow label={label}>
      <TextInput aria-label={label} value={value} onChange={onChange} className="w-64" />
    </FieldRow>
  );
}

function NumField({ label, value, onChange, path }: { label: string; value: number; onChange: (v: number | undefined) => void; path?: string }) {
  return (
    <FieldRow label={label} path={path}>
      <NumberInput aria-label={label} value={value} onChange={onChange} />
    </FieldRow>
  );
}
