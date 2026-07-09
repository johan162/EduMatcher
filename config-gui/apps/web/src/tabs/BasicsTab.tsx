import {
  DISCONNECT_BEHAVIOURS,
  PARTICIPANT_ROLES,
  createGateway,
  defaultDisconnectBehaviour,
  type DisconnectBehaviour,
  type ParticipantRole,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { uppercaseId } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { TagInput } from "@/components/fields/TagInput";
import { TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";

export function BasicsTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  const addSymbol = (symbol: string) =>
    update((d) => {
      if (!d.symbols[symbol]) {
        d.symbols[symbol] = { tickDecimals: d.tickDecimals };
        d.symbolOrder.push(symbol);
      }
    });

  const removeSymbol = (symbol: string) =>
    update((d) => {
      delete d.symbols[symbol];
      d.symbolOrder = d.symbolOrder.filter((s) => s !== symbol);
      for (const index of d.indices) {
        index.constituents = index.constituents.filter((c) => c !== symbol);
      }
      for (const combo of d.combos) {
        combo.legs = combo.legs.filter((leg) => leg.symbol !== symbol);
      }
    });

  return (
    <Panel
      tabId="basics"
      title="Basics"
      intro="Define the instruments that trade on your exchange and the gateway sessions that connect to it. At least one symbol and one gateway are required."
    >
      <Section
        title="Symbols"
        description="Ticker symbols traded on this exchange. Type and press Enter or comma; names are uppercased automatically."
      >
        <FieldRow
          label="Symbols"
          path="symbols"
          required
          help={{
            text: "The instrument universe. Every gateway can trade every symbol. Add at least one.",
            cliFlag: "--symbols",
          }}
        >
          <TagInput
            aria-label="Symbols"
            values={draft.symbolOrder}
            onAdd={addSymbol}
            onRemove={removeSymbol}
            transform={uppercaseId}
            placeholder="e.g. AAPL, MSFT, TSLA"
          />
        </FieldRow>
      </Section>

      <Section
        title="Gateways"
        description="Participant sessions permitted to connect. IDs are unique and uppercased. A MARKET_MAKER gateway enables quote seeding; an ADMIN gateway enables exchange-wide controls."
      >
        <FieldRow
          label="Gateway sessions"
          path="gateways"
          required
          help={{
            text: "Each row is a login session with a role. Roles: TRADER submits orders, MARKET_MAKER supplies quotes, ADMIN issues control commands.",
            cliFlag: "--gateways",
          }}
        >
          <div className="w-full">
            <div className="overflow-hidden rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
                  <tr>
                    <th className="px-3 py-2">ID *</th>
                    <th className="px-3 py-2">Role</th>
                    {canSee("I") && <th className="px-3 py-2">Disconnect</th>}
                    {canSee("I") && <th className="px-3 py-2">Description</th>}
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {draft.gateways.map((gateway, index) => (
                    <tr key={index} className="border-t border-border">
                      <td className="px-3 py-1.5">
                        <TextInput
                          aria-label={`Gateway ${index + 1} id`}
                          value={gateway.id}
                          onChange={(v) =>
                            update((d) => {
                              d.gateways[index]!.id = v;
                            })
                          }
                          onBlur={() =>
                            update((d) => {
                              d.gateways[index]!.id = uppercaseId(d.gateways[index]!.id);
                            })
                          }
                          className="w-32"
                        />
                      </td>
                      <td className="px-3 py-1.5">
                        <Select
                          aria-label={`Gateway ${index + 1} role`}
                          value={gateway.role}
                          onValueChange={(v) =>
                            update((d) => {
                              const g = d.gateways[index]!;
                              const previousDefault = defaultDisconnectBehaviour(g.role);
                              g.role = v as ParticipantRole;
                              // Keep disconnect in sync when it was still at the role default.
                              if (g.disconnectBehaviour === previousDefault) {
                                g.disconnectBehaviour = defaultDisconnectBehaviour(g.role);
                              }
                            })
                          }
                          options={PARTICIPANT_ROLES.map((r) => ({ value: r, label: r }))}
                        />
                      </td>
                      {canSee("I") && (
                        <td className="px-3 py-1.5">
                          <Select
                            aria-label={`Gateway ${index + 1} disconnect behaviour`}
                            value={gateway.disconnectBehaviour}
                            onValueChange={(v) =>
                              update((d) => {
                                d.gateways[index]!.disconnectBehaviour = v as DisconnectBehaviour;
                              })
                            }
                            options={DISCONNECT_BEHAVIOURS.map((b) => ({ value: b, label: b }))}
                          />
                        </td>
                      )}
                      {canSee("I") && (
                        <td className="px-3 py-1.5">
                          <TextInput
                            aria-label={`Gateway ${index + 1} description`}
                            value={gateway.description ?? ""}
                            onChange={(v) =>
                              update((d) => {
                                d.gateways[index]!.description = v || undefined;
                              })
                            }
                            className="w-full"
                          />
                        </td>
                      )}
                      <td className="px-3 py-1.5 text-right">
                        <button
                          type="button"
                          aria-label={`Remove gateway ${gateway.id || index + 1}`}
                          onClick={() =>
                            update((d) => {
                              d.gateways.splice(index, 1);
                            })
                          }
                          className="text-fg-subtle hover:text-error"
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                  {draft.gateways.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-3 py-3 text-center text-fg-subtle">
                        No gateways yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <button
              type="button"
              onClick={() =>
                update((d) => {
                  const id = `GW${String(d.gateways.length + 1).padStart(2, "0")}`;
                  d.gateways.push(createGateway(id));
                })
              }
              className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              + Add gateway
            </button>
          </div>
        </FieldRow>
      </Section>
    </Panel>
  );
}
