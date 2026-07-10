import {
  DISCONNECT_BEHAVIOURS,
  PARTICIPANT_ROLES,
  createGateway,
  defaultDisconnectBehaviour,
  type DisconnectBehaviour,
  type ParticipantRole,
} from "@edumatcher/schema";
import { useState } from "react";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { uppercaseId } from "@/lib/format";
import { Panel, Section } from "@/components/layout/Panel";
import { FieldRow } from "@/components/fields/FieldRow";
import { TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { SymbolEditorDialog } from "@/components/symbols/SymbolEditorDialog";

export function BasicsTab() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSymbol, setEditingSymbol] = useState<string | undefined>(undefined);

  const openCreate = () => {
    setEditingSymbol(undefined);
    setDialogOpen(true);
  };
  const openEdit = (symbol: string) => {
    setEditingSymbol(symbol);
    setDialogOpen(true);
  };

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
        description="Each symbol is a structured instrument with required reference prices. Use Add symbol to create one; edit any row to adjust prices and (for higher personas) precision, shares, and market-maker quotes."
      >
        <FieldRow
          label="Symbols"
          path="symbols"
          required
          help={{
            text: "The instrument universe. Every symbol needs a last buy and last sell reference price. Add at least one.",
            cliFlag: "--symbols",
          }}
        >
          <div className="w-full">
            <div className="overflow-hidden rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
                  <tr>
                    <th className="px-3 py-2">Symbol</th>
                    <th className="px-3 py-2">Last buy</th>
                    <th className="px-3 py-2">Last sell</th>
                    {canSee("I") && <th className="px-3 py-2">MM quotes</th>}
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {draft.symbolOrder.map((symbol) => {
                    const cfg = draft.symbols[symbol]!;
                    const missing =
                      cfg.lastBuyPrice === undefined ||
                      cfg.lastBuyPrice === null ||
                      cfg.lastSellPrice === undefined ||
                      cfg.lastSellPrice === null;
                    return (
                      <tr key={symbol} className="border-t border-border">
                        <td className="px-3 py-1.5 font-medium">{symbol}</td>
                        <td className="px-3 py-1.5">{cfg.lastBuyPrice ?? "—"}</td>
                        <td className="px-3 py-1.5">{cfg.lastSellPrice ?? "—"}</td>
                        {canSee("I") && (
                          <td className="px-3 py-1.5">{cfg.marketMakerQuotes?.length ?? 0}</td>
                        )}
                        <td className="px-3 py-1.5">
                          {missing ? (
                            <span className="text-warning">⚠ prices missing</span>
                          ) : (
                            <span className="text-success">✓ complete</span>
                          )}
                        </td>
                        <td className="px-3 py-1.5 text-right">
                          <button
                            type="button"
                            aria-label={`Edit ${symbol}`}
                            onClick={() => openEdit(symbol)}
                            className="mr-2 text-fg-subtle hover:text-fg"
                          >
                            ✎
                          </button>
                          <button
                            type="button"
                            aria-label={`Remove ${symbol}`}
                            onClick={() => removeSymbol(symbol)}
                            className="text-fg-subtle hover:text-error"
                          >
                            ×
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {draft.symbolOrder.length === 0 && (
                    <tr>
                      <td
                        colSpan={canSee("I") ? 6 : 5}
                        className="px-3 py-3 text-center text-fg-subtle"
                      >
                        No symbols yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <button
              type="button"
              onClick={openCreate}
              className="mt-2 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              + Add symbol
            </button>
          </div>
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

      <SymbolEditorDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={editingSymbol ? "edit" : "create"}
        symbolName={editingSymbol}
      />
    </Panel>
  );
}
