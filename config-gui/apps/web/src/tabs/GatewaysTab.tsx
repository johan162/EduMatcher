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
import { FieldRow, type FieldHelp } from "@/components/fields/FieldRow";
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
      intro="Optional network services around the engine: post-trade (fills/drop-copy), market-data (snapshots), BALF (binary access), drop-copy TCP relay, the centralized log server, and the REST/WebSocket API gateway. Enable only what your scenario needs. Ports are collision-checked across all gateways."
    >
      <Tabs.Root defaultValue="post-trade" className="mt-2">
        <Tabs.List className="mb-4 flex flex-wrap gap-1 border-b border-border">
          <Tabs.Trigger value="post-trade" className={TAB_TRIGGER}>Post-Trade</Tabs.Trigger>
          <Tabs.Trigger value="market-data" className={TAB_TRIGGER}>Market-Data</Tabs.Trigger>
          {canSee("E") && <Tabs.Trigger value="balf" className={TAB_TRIGGER}>BALF</Tabs.Trigger>}
          {canSee("E") && <Tabs.Trigger value="dc" className={TAB_TRIGGER}>Drop-Copy</Tabs.Trigger>}
          {canSee("E") && <Tabs.Trigger value="log-server" className={TAB_TRIGGER}>Log Server</Tabs.Trigger>}
          {canSee("E") && <Tabs.Trigger value="api" className={TAB_TRIGGER}>API</Tabs.Trigger>}
        </Tabs.List>

        <Tabs.Content value="post-trade"><PostTradePanel /></Tabs.Content>
        <Tabs.Content value="market-data"><MarketDataPanel /></Tabs.Content>
        {canSee("E") && <Tabs.Content value="balf"><BalfPanel /></Tabs.Content>}
        {canSee("E") && <Tabs.Content value="dc"><DcPanel /></Tabs.Content>}
        {canSee("E") && <Tabs.Content value="log-server"><LogServerPanel /></Tabs.Content>}
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
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} help={{ text: "Service name reported to connecting RALF clients (e.g. in a WELCOME/identity line).", cliFlag: "--post-trade-name" }} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} help={{ text: "Network interface the post-trade (RALF) TCP gateway listens on. Use 127.0.0.1 for loopback-only.", cliFlag: "--post-trade-bind-address" }} />
          <NumField label="Port" path="postTradeGateway.port" value={g.port} onChange={(v) => set((gw) => (gw.port = v ?? gw.port))} help={{ text: "TCP port RALF post-trade subscribers connect to for the replayable trade feed.", cliFlag: "--post-trade-port" }} />
          <NumField label="Replay retention (sec)" value={g.replayRetentionSec} onChange={(v) => set((gw) => (gw.replayRetentionSec = v ?? gw.replayRetentionSec))} help={{ text: "How long past trade records stay available for sequence-gap replay after a client reconnects.", cliFlag: "--post-trade-replay-retention-sec" }} />
          <NumField label="Heartbeat interval (sec)" value={g.heartbeatIntervalSec} onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))} help={{ text: "Seconds between HB keepalive lines when no other outbound traffic is pending.", cliFlag: "--post-trade-heartbeat-interval-sec" }} />
          <NumField label="Idle timeout (sec)" value={g.idleTimeoutSec} onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))} help={{ text: "Disconnect threshold when a connected client sends no traffic for this many seconds.", cliFlag: "--post-trade-idle-timeout-sec" }} />
          <NumField label="Max client queue" value={g.maxClientQueue} onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))} help={{ text: "Per-client outbound line buffer capacity before the client is treated as slow and disconnected.", cliFlag: "--post-trade-max-client-queue" }} />
          <FieldRow label="Allowed roles" help={{ text: "Which participant roles may subscribe to the post-trade feed (e.g. clearing, drop-copy, or audit systems).", cliFlag: "--post-trade-allowed-roles" }}>
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
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} help={{ text: "Service name reported to CALF clients as WELCOME|GW=.", cliFlag: "--market-data-name" }} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} help={{ text: "Network interface the market-data (CALF) TCP gateway listens on. Use 127.0.0.1 for loopback-only.", cliFlag: "--market-data-bind-address" }} />
          <NumField label="Port" path="marketDataGateway.port" value={g.port} onChange={(v) => set((gw) => (gw.port = v ?? gw.port))} help={{ text: "TCP port CALF subscribers connect to for order-book snapshots, trade prints, and session-state changes.", cliFlag: "--market-data-port" }} />
          <NumField label="Heartbeat interval (sec)" value={g.heartbeatIntervalSec} onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))} help={{ text: "Seconds between HB keepalive lines, advertised to clients as WELCOME|HBINT=.", cliFlag: "--market-data-heartbeat-interval-sec" }} />
          <NumField label="Idle timeout (sec)" value={g.idleTimeoutSec} onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))} help={{ text: "Disconnect threshold when a connected client sends no traffic for this many seconds.", cliFlag: "--market-data-idle-timeout-sec" }} />
          <NumField label="Replay window (sec)" value={g.replayWindowSec} onChange={(v) => set((gw) => (gw.replayWindowSec = v ?? gw.replayWindowSec))} help={{ text: "How far back a reconnecting client can request a sequence-gap replay, advertised as WELCOME|REPLAY=.", cliFlag: "--market-data-replay-window-sec" }} />
          <NumField label="Max symbols per client" value={g.maxSymbolsPerClient} onChange={(v) => set((gw) => (gw.maxSymbolsPerClient = v ?? gw.maxSymbolsPerClient))} help={{ text: "Upper bound on how many symbols a single client connection may subscribe to at once.", cliFlag: "--market-data-max-symbols-per-client" }} />
          <NumField label="Max client queue" value={g.maxClientQueue} onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))} help={{ text: "Per-client outbound line buffer capacity before the client is treated as slow and disconnected.", cliFlag: "--market-data-max-client-queue" }} />
          <NumField label="Depth levels" value={g.depthLevels} onChange={(v) => set((gw) => (gw.depthLevels = v ?? gw.depthLevels))} help={{ text: "Number of aggregated price levels per side included in DEPTH channel snapshots and updates.", cliFlag: "--market-data-depth-levels" }} />
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
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} help={{ text: "Service name reported to connecting BALF clients.", cliFlag: "--balf-name" }} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} help={{ text: "Network interface the BALF binary TCP gateway listens on. Use 127.0.0.1 for loopback-only.", cliFlag: "--balf-bind-address" }} />
          <NumField label="Port" path="balfGateway.port" value={g.port} onChange={(v) => set((gw) => (gw.port = v ?? gw.port))} help={{ text: "TCP port BALF clients connect to for fixed-width binary order-entry frames.", cliFlag: "--balf-port" }} />
          <NumField label="Heartbeat interval (sec)" value={g.heartbeatIntervalSec} onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))} help={{ text: "Seconds between HB keepalive frames when no other outbound traffic is pending.", cliFlag: "--balf-heartbeat-interval-sec" }} />
          <NumField label="Heartbeat timeout (sec)" value={g.heartbeatTimeoutSec} onChange={(v) => set((gw) => (gw.heartbeatTimeoutSec = v ?? gw.heartbeatTimeoutSec))} help={{ text: "How long to wait for an expected heartbeat before treating the connection as dead.", cliFlag: "--balf-heartbeat-timeout-sec" }} />
          <NumField label="Idle timeout (sec)" value={g.idleTimeoutSec} onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))} help={{ text: "Disconnect threshold when a connected client sends no traffic for this many seconds.", cliFlag: "--balf-idle-timeout-sec" }} />
          <NumField label="Auth timeout (sec)" value={g.authTimeoutSec} onChange={(v) => set((gw) => (gw.authTimeoutSec = v ?? gw.authTimeoutSec))} help={{ text: "How long a newly connected client has to complete authentication before being disconnected.", cliFlag: "--balf-auth-timeout-sec" }} />
          <NumField label="Max connections" value={g.maxConnections} onChange={(v) => set((gw) => (gw.maxConnections = v ?? gw.maxConnections))} help={{ text: "Maximum number of simultaneous BALF client connections accepted.", cliFlag: "--balf-max-connections" }} />
          <NumField label="Max client queue" value={g.maxClientQueue} onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))} help={{ text: "Per-client outbound frame buffer capacity before the client is treated as slow and disconnected.", cliFlag: "--balf-max-client-queue" }} />
          <NumField label="Max messages/sec" value={g.maxMessagesPerSecond} onChange={(v) => set((gw) => (gw.maxMessagesPerSecond = v ?? gw.maxMessagesPerSecond))} help={{ text: "Per-client inbound message rate limit before excess messages are rejected.", cliFlag: "--balf-max-messages-per-second" }} />
          <NumField label="Max errors before disconnect" value={g.maxErrorsBeforeDisconnect} onChange={(v) => set((gw) => (gw.maxErrorsBeforeDisconnect = v ?? gw.maxErrorsBeforeDisconnect))} help={{ text: "How many protocol errors a client may cause within the error window before being disconnected.", cliFlag: "--balf-max-errors-before-disconnect" }} />
          <NumField label="Error window (sec)" value={g.errorWindowSec} onChange={(v) => set((gw) => (gw.errorWindowSec = v ?? gw.errorWindowSec))} help={{ text: "Rolling time window over which protocol errors are counted toward the disconnect threshold.", cliFlag: "--balf-error-window-sec" }} />
          <FieldRow label="Duplicate session policy" help={{ text: "What happens when a gateway ID that's already connected tries to connect again: reject the new session, or evict the old one.", cliFlag: "--balf-duplicate-session-policy" }}>
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

function DcPanel() {
  const g = useDraftStore((s) => s.draft.dcGateway);
  const update = useDraftStore((s) => s.update);
  const set = (fn: (gw: typeof g) => void) => update((d) => fn(d.dcGateway));

  return (
    <div>
      <EnableRow
        enabled={g.enabled}
        onToggle={(v) => set((gw) => (gw.enabled = v))}
        label="Enable drop-copy gateway"
        flag="--dc-gateway"
      />
      {g.enabled && (
        <>
          <TextField label="Name" value={g.name} onChange={(v) => set((gw) => (gw.name = v))} help={{ text: "Service name echoed in WELCOME messages to connecting DC1 clients.", cliFlag: "--dc-name" }} />
          <TextField label="Bind address" value={g.bindAddress} onChange={(v) => set((gw) => (gw.bindAddress = v))} help={{ text: "Network interface/address the drop-copy TCP gateway listens on. Use 127.0.0.1 for loopback-only.", cliFlag: "--dc-bind-address" }} />
          <NumField
            label="Port"
            path="dcGateway.port"
            value={g.port}
            onChange={(v) => set((gw) => (gw.port = v ?? gw.port))}
            help={{ text: "TCP port DC1 clients connect to for live fill notifications.", cliFlag: "--dc-port" }}
          />
          <NumField
            label="Heartbeat interval (sec)"
            value={g.heartbeatIntervalSec}
            onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))}
            help={{ text: "Seconds between HB keepalive lines when no other outbound traffic is pending.", cliFlag: "--dc-heartbeat-interval-sec" }}
          />
          <NumField
            label="Idle timeout (sec)"
            value={g.idleTimeoutSec}
            onChange={(v) => set((gw) => (gw.idleTimeoutSec = v ?? gw.idleTimeoutSec))}
            help={{ text: "Disconnect threshold when a connected client sends no traffic for this many seconds.", cliFlag: "--dc-idle-timeout-sec" }}
          />
          <NumField
            label="Max client queue"
            value={g.maxClientQueue}
            onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))}
            help={{ text: "Per-client outbound line buffer capacity before the client is treated as slow and dropped.", cliFlag: "--dc-max-client-queue" }}
          />
        </>
      )}
    </div>
  );
}

function LogServerPanel() {
  const g = useDraftStore((s) => s.draft.logServer);
  const update = useDraftStore((s) => s.update);
  const set = (fn: (gw: typeof g) => void) => update((d) => fn(d.logServer));

  return (
    <div>
      <EnableRow
        enabled={g.enabled}
        onToggle={(v) => set((gw) => (gw.enabled = v))}
        label="Enable log server"
        flag="--log-server"
      />
      {g.enabled && (
        <>
          <TextField
            label="Name"
            value={g.name}
            onChange={(v) => set((gw) => (gw.name = v))}
            help={{ text: "Server name echoed in the LALF WELCOME|SRV= field.", cliFlag: "--log-server-name" }}
          />
          <TextField
            label="Bind address"
            value={g.bindAddress}
            onChange={(v) => set((gw) => (gw.bindAddress = v))}
            help={{ text: "Network interface the centralized log collector listens on. Use 127.0.0.1 for loopback-only.", cliFlag: "--log-server-bind-address" }}
          />
          <NumField
            label="Port"
            path="logServer.port"
            value={g.port}
            onChange={(v) => set((gw) => (gw.port = v ?? gw.port))}
            help={{ text: "TCP port every other pm-* process connects to for centralized logging (LALF).", cliFlag: "--log-server-port" }}
          />
          <TextField
            label="Database path"
            value={g.dbPath}
            onChange={(v) => set((gw) => (gw.dbPath = v))}
            help={{ text: "SQLite database path where log_events/processes/server_stats are stored, queried by pm-log-cli.", cliFlag: "--log-server-db-path" }}
          />
          <FieldRow
            label="Retention (days)"
            path="logServer.retentionDays"
            help={{ text: "Prune log_events rows older than this many days, once per hour. Clear this field (or set 0) for unbounded retention.", cliFlag: "--log-server-retention-days" }}
          >
            <NumberInput
              aria-label="Retention (days)"
              value={g.retentionDays}
              min={0}
              onChange={(v) => set((gw) => (gw.retentionDays = v ?? null))}
            />
          </FieldRow>
          <NumField
            label="Max message bytes"
            value={g.maxMessageBytes}
            onChange={(v) => set((gw) => (gw.maxMessageBytes = v ?? gw.maxMessageBytes))}
            help={{ text: "Maximum LOG payload size before truncation. Oversized messages are truncated and stored, never dropped.", cliFlag: "--log-server-max-message-bytes" }}
          />
          <NumField
            label="Max client queue"
            value={g.maxClientQueue}
            onChange={(v) => set((gw) => (gw.maxClientQueue = v ?? gw.maxClientQueue))}
            help={{ text: "Per-connection outbound backlog limit before backpressure is applied.", cliFlag: "--log-server-max-client-queue" }}
          />
          <NumField
            label="Write batch size"
            value={g.writeBatchSize}
            onChange={(v) => set((gw) => (gw.writeBatchSize = v ?? gw.writeBatchSize))}
            help={{ text: "Maximum rows per SQLite transaction in the background writer thread.", cliFlag: "--log-server-write-batch-size" }}
          />
          <NumField
            label="Write batch interval (ms)"
            value={g.writeBatchIntervalMs}
            onChange={(v) => set((gw) => (gw.writeBatchIntervalMs = v ?? gw.writeBatchIntervalMs))}
            help={{ text: "Maximum time between writer-thread flushes, whichever comes first with the write batch size.", cliFlag: "--log-server-write-batch-interval-ms" }}
          />
          <NumField
            label="Heartbeat interval (sec)"
            value={g.heartbeatIntervalSec}
            onChange={(v) => set((gw) => (gw.heartbeatIntervalSec = v ?? gw.heartbeatIntervalSec))}
            help={{ text: "How often a connected client must send something (a LOG or HB message) to stay considered alive. The server itself never sends heartbeats — LALF's HB is client-to-server only — but it disconnects a client after 2× this interval of total silence. This value is sent to clients in WELCOME|HBINT= so they know the expected cadence.", cliFlag: "--log-server-heartbeat-interval-sec" }}
          />
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

          <TextField label="Instance name" value={gw.name} onChange={(v) => update((d) => (d.apiGateways[i]!.name = v))} help={{ text: "Key this instance is generated under in api_gateways.<NAME>. Must be unique across instances.", cliFlag: "--api-gateway-name" }} />
          <TextField label="Host" value={gw.host} onChange={(v) => update((d) => (d.apiGateways[i]!.host = v))} help={{ text: "Network interface this instance's HTTP/WebSocket server binds to.", cliFlag: "--api-gateway-host" }} />
          <NumField label="Port" path={`apiGateways.${gw.name}.port`} value={gw.port} onChange={(v) => update((d) => (d.apiGateways[i]!.port = v ?? gw.port))} help={{ text: "TCP port this instance's REST/WebSocket server listens on.", cliFlag: "--api-gateway-port" }} />

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

          <FieldRow label="Swagger UI" help={{ text: "Serve interactive /docs and /openapi.json pages alongside the API.", cliFlag: "--api-gateway-swagger-enabled" }}>
            <Switch aria-label="Swagger UI enabled" checked={gw.swaggerEnabled} onCheckedChange={(v) => update((d) => (d.apiGateways[i]!.swaggerEnabled = v))} />
          </FieldRow>
          <FieldRow label="Log level" help={{ text: "Minimum severity of this instance's own process logging: debug, info, warning, or error.", cliFlag: "--api-gateway-log-level" }}>
            <Select
              aria-label="Log level"
              value={gw.logLevel}
              onValueChange={(v) => update((d) => (d.apiGateways[i]!.logLevel = v as ApiLogLevel))}
              options={API_LOG_LEVELS.map((l) => ({ value: l, label: l }))}
            />
          </FieldRow>
          <TextField label="Stats DB path" value={gw.statsDb} onChange={(v) => update((d) => (d.apiGateways[i]!.statsDb = v))} help={{ text: "SQLite database this instance reads for /history/* endpoints (the same file pm-stats writes).", cliFlag: "--api-gateway-stats-db" }} />
          <div className="flex flex-wrap gap-4">
            <NumField label="Rate limit writes/sec" value={gw.rateLimitWritesPerSecond} onChange={(v) => update((d) => (d.apiGateways[i]!.rateLimitWritesPerSecond = v ?? gw.rateLimitWritesPerSecond))} help={{ text: "Sustained per-key limit on order-entry write requests per second.", cliFlag: "--api-gateway-rate-limit-writes-per-second" }} />
            <NumField label="Rate limit burst" value={gw.rateLimitBurst} onChange={(v) => update((d) => (d.apiGateways[i]!.rateLimitBurst = v ?? gw.rateLimitBurst))} help={{ text: "Short-term burst allowance above the sustained write rate limit, per key.", cliFlag: "--api-gateway-rate-limit-burst" }} />
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

function TextField({ label, value, onChange, help }: { label: string; value: string; onChange: (v: string) => void; help?: FieldHelp }) {
  return (
    <FieldRow label={label} help={help}>
      <TextInput aria-label={label} value={value} onChange={onChange} className="w-64" />
    </FieldRow>
  );
}

function NumField({ label, value, onChange, path, help }: { label: string; value: number; onChange: (v: number | undefined) => void; path?: string; help?: FieldHelp }) {
  return (
    <FieldRow label={label} path={path} help={help}>
      <NumberInput aria-label={label} value={value} onChange={onChange} />
    </FieldRow>
  );
}
