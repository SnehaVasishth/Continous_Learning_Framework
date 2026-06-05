import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api, HitlOperator, HitlSummary } from "../api";
import { ConfidenceBar, IntentPill, LangPill, StatusPill, TierPill } from "../components/Pills";
import { Button, Chip, Eyebrow, LinkButton, PageHeader, Section, Surface } from "../components/ui";

const ACTION_LABELS: Record<string, string> = {
  create_order_acknowledgment: "Acknowledge purchase order",
  convert_quote_to_order: "Convert quote to order",
  release_hold: "Release order from hold",
  reschedule_order: "Reschedule shipment",
  ssd_change_routed: "Reschedule shipment (SSD change)",
  change_delivery: "Change delivery details",
  amend_trade_order: "Amend trade order",
  create_work_order: "Create work order",
  update_work_order: "Update work order",
  report_wo_status: "Report work-order status",
  draft_service_contract_quote: "Draft service contract quote",
  create_service_contract: "Create service contract",
  draft_reply: "Draft customer reply",
  route_to_csr: "Route to CSR",
};

const ACTION_BLURBS: Record<string, string> = {
  create_order_acknowledgment: "Create the SOA, log the PO, and send the acknowledgment to the customer.",
  convert_quote_to_order: "Convert the matched quote into a sales order in ERP, then send the customer the SOA.",
  release_hold: "Confirm the hold can be lifted on the referenced order in ERP and notify the customer it is shipping.",
  reschedule_order: "Update the requested ship date on the referenced order in ERP and notify the customer.",
  ssd_change_routed: "Factory loop will propose a new ship date. CSR confirms before applying in Oracle and notifying the customer.",
  change_delivery: "Update ship-to address, carrier, Incoterm, or delivery instructions on the referenced order in ERP, then confirm with the customer.",
  amend_trade_order: "Apply the quantity, price, or line changes to the referenced order in ERP and confirm with the customer.",
  create_work_order: "Open a service work order in ERP and notify the customer of the next available slot.",
  update_work_order: "Apply the requested change to the existing work order and confirm with the customer.",
  report_wo_status: "Compile current status of the customer's open work orders and reply with the summary.",
  draft_service_contract_quote: "Generate a service contract quote for the requested coverage and assets, then send to the customer for signature.",
  create_service_contract: "Create the service contract record in ERP and notify the customer it is active.",
  draft_reply: "Send the drafted reply to the customer.",
  route_to_csr: "Route to CSR for handling.",
};

const LANG_NAMES: Record<string, string> = { en: "English", es: "Spanish", ja: "Japanese" };
const LANG_FLAGS: Record<string, string> = { en: "🇬🇧", es: "🇪🇸", ja: "🇯🇵" };

const INTENT_LABELS: Record<string, string> = {
  po_intake: "PO intake",
  quote_to_order: "Quote → Order",
  trade_change_order: "Trade change order",
  hold_release: "Hold release",
  delivery_change: "Delivery change",
  ssd_change_request: "SSD change",
  service_order: "Service order",
  wo_update_request: "WO update",
  wo_status_inquiry: "WO status inquiry",
  service_contract_request: "Service contract",
  general_inquiry: "General inquiry",
  spam: "Spam",
};

export function HitlPage() {
  const [items, setItems] = useState<HitlSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<HitlSummary | null>(null);
  const [extracted, setExtracted] = useState<any>({});
  const [rawJson, setRawJson] = useState<string>("");
  const [rawMode, setRawMode] = useState<boolean>(false);
  const [previewRaw, setPreviewRaw] = useState<boolean>(false);
  const [replySubject, setReplySubject] = useState<string>("");
  const [replyBody, setReplyBody] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  // Confirmation acknowledgments: each next_step in preview.action_required
  // becomes a real checkbox the CSR must tick before Approve is enabled.
  // Cleared whenever the selected HITL task changes so a new case starts
  // with all boxes unchecked.
  const [acks, setAcks] = useState<boolean[]>([]);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [searchText, setSearchText] = useState<string>("");
  const [chipReason, setChipReason] = useState<string>("");
  const [chipIntent, setChipIntent] = useState<string>("");
  const [chipTier, setChipTier] = useState<string>("");
  const [operators, setOperators] = useState<HitlOperator[]>([]);
  const [assigning, setAssigning] = useState(false);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const reasonFilter = searchParams.get("reason") || "";
  const pipelineFilter = searchParams.get("pipeline") || "";

  const refresh = async () => {
    const data = await api.listHitl({
      status: "pending",
      q: searchText || undefined,
      reason: chipReason || undefined,
      intent: chipIntent || undefined,
      tier: chipTier || undefined,
    });
    setItems(data);
  };

  // Filter the queue down to a reason or a specific pipeline_id when the
  // dashboard / activity row clicks through with ?reason= or ?pipeline=.
  const filteredItems = useMemo(() => {
    return items.filter((t) => {
      if (reasonFilter && (t.reason || "") !== reasonFilter) return false;
      if (pipelineFilter && String(t.pipeline?.id || "") !== pipelineFilter) return false;
      return true;
    });
  }, [items, reasonFilter, pipelineFilter]);

  // Deep-link from the Trace page banner: ?pipeline=N narrows the queue to
  // the matching task and auto-opens it in the detail panel so the CSR lands
  // directly on the activity rather than the overall queue. We only auto-
  // select once per query value to keep the operator in control after focus.
  const [autoSelectedForPipeline, setAutoSelectedForPipeline] = useState<string | null>(null);
  useEffect(() => {
    if (!pipelineFilter) return;
    if (autoSelectedForPipeline === pipelineFilter) return;
    const match = filteredItems[0];
    if (match) {
      setSelectedId(match.id);
      setAutoSelectedForPipeline(pipelineFilter);
    }
  }, [filteredItems, pipelineFilter, autoSelectedForPipeline]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [searchText, chipReason, chipIntent, chipTier]);

  useEffect(() => {
    api.listHitlOperators().then((r) => setOperators(r.users || [])).catch(() => setOperators([]));
  }, []);

  const handleAssign = async (taskId: number, userId: string | null) => {
    if (!detail) return;
    setAssigning(true);
    try {
      const user = userId ? operators.find((u) => u.id === userId) : null;
      const updated = await api.assignHitl(taskId, {
        user_id: user?.id || null,
        user_name: user?.name || null,
        queue: detail.owner_queue || null,
      });
      setDetail(updated);
      setItems((prev) => prev.map((t) => (t.id === taskId ? { ...t, assignee: updated.assignee } : t)));
      setToast({ kind: "ok", msg: userId ? `Assigned to ${user?.name}` : "Unassigned" });
      setTimeout(() => setToast(null), 2500);
    } catch (e: any) {
      setToast({ kind: "err", msg: `Assignment failed: ${e?.message || e}` });
      setTimeout(() => setToast(null), 3500);
    } finally {
      setAssigning(false);
    }
  };

  const copyShareLink = () => {
    if (!detail) return;
    const url = `${window.location.origin}${import.meta.env.BASE_URL}hitl?task=${detail.id}`.replace(/([^:]\/)\/+/g, "$1");
    navigator.clipboard.writeText(url).then(() => {
      setToast({ kind: "ok", msg: "Link copied" });
      setTimeout(() => setToast(null), 2000);
    });
  };

  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      setExtracted({});
      setRawJson("");
      setReplySubject("");
      setReplyBody("");
      setNote("");
      setRawMode(false);
      setPreviewRaw(false);
      setAcks([]);
      return;
    }
    api.getHitl(selectedId).then((d) => {
      setDetail(d);
      const ex = d.payload?.extracted ?? {};
      setExtracted(ex);
      setRawJson(JSON.stringify(ex, null, 2));
      setReplySubject(d.reply?.subject || "");
      setReplyBody(d.reply?.body || "");
      setRawMode(false);
      setPreviewRaw(false);
      const steps = d.payload?.preview?.action_required?.next_steps;
      setAcks(Array.isArray(steps) ? steps.map(() => false) : []);
    });
  }, [selectedId]);

  const intent = detail?.pipeline?.intent || "";
  const isPoIntent = intent === "po_intake" || intent === "quote_to_order";
  // === v1.2 HITL-REPLY-GATING START ===
  // Decision-driven gating: show the drafted reply whenever the proposed
  // action requires a customer-facing email (release_hold, change_delivery,
  // draft_reply, etc.), regardless of intent. Terminal redirect / log-only
  // actions (route_to_csr, redirect) skip the reply card. Falls back to an
  // intent-based denylist for cases where decision.action wasn't recorded.
  const decisionAction: string =
    (detail?.payload as any)?.decision?.action ||
    (detail?.pipeline as any)?.decision_action ||
    "";
  const REPLY_REQUIRED_ACTIONS = new Set([
    "create_order_acknowledgment",
    "convert_quote_to_order",
    "release_hold",
    "reschedule_order",
    "ssd_change_routed",
    "change_delivery",
    "amend_trade_order",
    "create_work_order",
    "update_work_order",
    "report_wo_status",
    "draft_service_contract_quote",
    "create_service_contract",
    "draft_reply",
  ]);
  const NO_REPLY_INTENTS_FALLBACK = new Set([
    "spam", "out_of_scope", "kso", "collections",
    "portal_admin", "brazil_tax", "undeliverable",
  ]);
  const showDraftedReply = decisionAction
    ? REPLY_REQUIRED_ACTIONS.has(decisionAction)
    : !!intent && !NO_REPLY_INTENTS_FALLBACK.has(intent);
  const replyBodyEmpty = !((detail?.reply?.body || "").trim() || (detail?.reply?.subject || "").trim());
  // === v1.2 HITL-REPLY-GATING END ===

  const updateExtracted = (next: any) => {
    setExtracted(next);
    setRawJson(JSON.stringify(next, null, 2));
  };

  const onRawChange = (s: string) => {
    setRawJson(s);
    try {
      setExtracted(JSON.parse(s));
    } catch {}
  };

  const replyDirty = useMemo(() => {
    return (
      (detail?.reply?.subject || "") !== replySubject || (detail?.reply?.body || "") !== replyBody
    );
  }, [detail, replySubject, replyBody]);

  const submit = async (action: "approve" | "edit_and_approve" | "reject") => {
    if (!selectedId) return;
    let parsedEdits: any = undefined;
    if (action === "edit_and_approve") {
      if (rawMode) {
        try {
          parsedEdits = JSON.parse(rawJson);
        } catch {
          alert("Raw JSON is invalid");
          return;
        }
      } else {
        parsedEdits = extracted;
      }
    }
    setSubmitting(true);
    try {
      const res = await api.resolveHitl(selectedId, {
        action,
        note,
        edits: parsedEdits,
        reply:
          action !== "reject" && replyDirty
            ? { subject: replySubject, body: replyBody }
            : undefined,
      });
      if (action !== "reject") {
        const d = res.delivery || {};
        const recipient = res.recipient || "customer";
        if (d.delivery_status === "sent") {
          showToast("ok", `Reply sent to ${recipient}`);
        } else if (d.delivery_status === "blocked_by_demo_lock" || d.delivery_status === "blocked_by_kill_switch") {
          // Demo mode: outbound is blocked at the backend by config.DEMO_TRANSMIT_LOCKED.
          // Surface this as a successful action so the demo flow reads as
          // end-to-end without claiming a real email left the system.
          // The trace + communication log still record the truth (delivery_status, blocked reason).
          showToast("ok", `Reply queued for ${recipient} (demo mode: outbound transmission is locked; the case is fully processed and logged)`);
        } else if (d.delivery_status === "skipped") {
          showToast("err", `Action applied but no recipient address. No email sent.`);
        } else {
          showToast("err", `Send failed: ${d.error || "unknown SMTP error"}`);
        }
      } else {
        showToast("ok", "Rejected. Nothing sent to customer.");
      }
      setSelectedId(null);
      await refresh();
    } finally {
      setSubmitting(false);
    }
  };

  const showToast = (kind: "ok" | "err", msg: string) => {
    setToast({ kind, msg });
    setTimeout(() => setToast(null), 5000);
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="HITL Queue"
        subtitle="Low-confidence requests and one-click confirmations awaiting CSR review. Each task includes a context-specific playbook so a CSR can resolve it without leaving this page."
        badges={
          <>
            <Chip tone={filteredItems.length > 0 ? "warning" : "success"}>
              {filteredItems.length}{(reasonFilter || pipelineFilter) ? ` of ${items.length}` : ""} pending
            </Chip>
            {(reasonFilter || pipelineFilter) && (
              <button onClick={() => navigate("/hitl")} className="text-[11px] text-zbrain hover:underline">
                Clear filter ({reasonFilter || `pipeline #${pipelineFilter}`})
              </button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-12 gap-5">
        {/* ------- Queue list ------- */}
        <Surface className="col-span-5 overflow-hidden flex flex-col" variant="resting">
          <div className="px-5 pt-4 pb-2 flex items-center justify-between">
            <Eyebrow>Queue · {filteredItems.length}</Eyebrow>
            <button
              onClick={refresh}
              className="text-[11px] text-zbrain hover:underline"
              title="Refresh"
            >
              ↻ refresh
            </button>
          </div>
          <div className="px-5 pb-3 space-y-2">
            <input
              type="text"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="Search by subject, customer, PO, intent..."
              className="w-full text-[12px] bg-zbrain-surface border border-zbrain-divider rounded-md px-3 py-2 outline-none focus:border-zbrain focus:bg-white"
            />
            <div className="flex items-center gap-1.5 flex-wrap text-[10px]">
              {(["unknown_customer_in_salesforce", "awaiting_one_click", "low_confidence", "aioa_fallout", "salesforce_not_configured"].filter((r) => items.some((t) => t.reason === r))).map((r) => (
                <button
                  key={r}
                  onClick={() => setChipReason(chipReason === r ? "" : r)}
                  className={`pill cursor-pointer ${chipReason === r ? "bg-zbrain text-white" : "bg-zbrain-50 text-zbrain hover:bg-zbrain-100"}`}
                >
                  {r.replaceAll("_", " ")}
                </button>
              ))}
              {(["po_intake", "quote_to_order", "service_order", "service_contract_request", "wo_status_inquiry", "wo_update_request", "trade_change_order"].filter((i) => items.some((t) => t.pipeline?.intent === i))).map((i) => (
                <button
                  key={i}
                  onClick={() => setChipIntent(chipIntent === i ? "" : i)}
                  className={`pill cursor-pointer ${chipIntent === i ? "bg-zbrain text-white" : "bg-violet-50 text-violet-700 hover:bg-violet-100"}`}
                >
                  {INTENT_LABELS[i] || i.replaceAll("_", " ")}
                </button>
              ))}
              {(["L2_HITL", "L3_ONE_CLICK", "L4_AUTO"].filter((tt) => items.some((t) => t.pipeline?.autonomy_tier === tt))).map((tt) => (
                <button
                  key={tt}
                  onClick={() => setChipTier(chipTier === tt ? "" : tt)}
                  className={`pill cursor-pointer ${chipTier === tt ? "bg-zbrain text-white" : "bg-amber-50 text-amber-700 hover:bg-amber-100"}`}
                >
                  {tt.replace("_", " ")}
                </button>
              ))}
              {(chipReason || chipIntent || chipTier || searchText) && (
                <button
                  onClick={() => { setChipReason(""); setChipIntent(""); setChipTier(""); setSearchText(""); }}
                  className="text-[10px] text-zbrain-muted hover:text-zbrain-ink underline ml-1"
                >
                  clear all
                </button>
              )}
            </div>
          </div>
          <div className="flex-1 max-h-[calc(100vh-260px)] overflow-auto">
            {filteredItems.length === 0 && (
              <div className="px-6 py-16 text-center">
                <div className="text-zbrain-muted/50 text-3xl mb-2">✓</div>
                <div className="text-[14px] font-medium text-zbrain-ink">{items.length === 0 ? "Queue is clear" : "Nothing matches this filter"}</div>
                <div className="text-[12px] text-zbrain-muted mt-1">
                  {items.length === 0 ? "Every request has been resolved." : "Try clearing the filter to see all pending items."}
                </div>
              </div>
            )}
            {filteredItems.map((t) => {
              const isSel = selectedId === t.id;
              const conf = t.pipeline?.confidence;
              const reasonClean = (t.reason || "").replaceAll("_", " ");
              return (
                <button
                  key={t.id}
                  onClick={() => setSelectedId(t.id)}
                  className={`w-full text-left px-5 py-3.5 transition-colors duration-150
                    ${isSel
                      ? "bg-zbrain-50/80 border-l-2 border-zbrain"
                      : "border-l-2 border-transparent hover:bg-zbrain-surface"
                    }`}
                  style={{ transitionTimingFunction: "var(--ease-spring)" }}
                >
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[10px] font-mono font-medium px-1.5 py-0.5 rounded bg-zbrain-50 text-zbrain">
                          {t.display_id || `HITL-${String(t.id).padStart(5, "0")}`}
                        </span>
                        {t.assignee?.name && (
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700">
                            {t.assignee.name}
                          </span>
                        )}
                      </div>
                      <div className="text-[14px] font-semibold text-zbrain-ink truncate leading-snug">
                        {t.email?.subject || "(no subject)"}
                      </div>
                      <div className="text-[12px] text-zbrain-muted truncate mt-0.5 font-mono">
                        {t.email?.from}
                      </div>
                    </div>
                    {conf != null && (
                      <div className="text-right shrink-0">
                        <div className="text-[16px] font-semibold tabular-nums tracking-tight text-zbrain-ink">
                          {Math.round(conf * 100)}%
                        </div>
                        <div className="text-[9px] uppercase tracking-wider text-zbrain-muted/70">
                          confidence
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
                    {t.pipeline?.intent && (
                      <Chip tone="info">{INTENT_LABELS[t.pipeline.intent] || t.pipeline.intent.replaceAll("_", " ")}</Chip>
                    )}
                    {(t.pipeline?.language || t.email?.language_hint) && (
                      <Chip tone="violet">
                        {(t.pipeline?.language || t.email?.language_hint || "").toUpperCase()}
                      </Chip>
                    )}
                    {t.pipeline?.autonomy_tier && (
                      <Chip tone={t.pipeline.autonomy_tier === "L4_AUTO" ? "success" : t.pipeline.autonomy_tier === "L3_ONE_CLICK" ? "info" : "warning"}>
                        {t.pipeline.autonomy_tier.replace("_", " ")}
                      </Chip>
                    )}
                    {(t as any)?.owner_label && (
                      <Chip tone="emphasis" className="text-[10px]">
                        {(t as any).owner_label}
                      </Chip>
                    )}
                    <Chip tone="warning" className="ml-auto">
                      {reasonClean}
                    </Chip>
                  </div>
                </button>
              );
            })}
          </div>
        </Surface>

        {/* ------- Detail panel ------- */}
        <div className="col-span-7 space-y-4">
          {!detail ? (
            <Surface className="px-8 py-20 text-center" variant="resting">
              <div className="text-zbrain-muted/40 text-5xl mb-3">←</div>
              <div className="text-[15px] font-medium text-zbrain-ink">Select a task</div>
              <div className="text-[13px] text-zbrain-muted mt-1.5 max-w-sm mx-auto">
                Pick any item from the queue on the left to see the full request, the proposed action, and the
                CSR playbook for resolving it.
              </div>
            </Surface>
          ) : (
            <>
              {/* Detail header */}
              <Surface variant="resting">
                <Section padding="default">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded bg-zbrain-50 text-zbrain">
                          {detail.display_id || `HITL-${String(detail.id).padStart(5, "0")}`}
                        </span>
                        <button
                          onClick={copyShareLink}
                          className="text-[11px] text-zbrain-muted hover:text-zbrain underline"
                          title="Copy a shareable link to this task"
                        >
                          copy link
                        </button>
                      </div>
                      <h2 className="text-[18px] font-semibold tracking-tight text-zbrain-ink leading-snug">
                        {detail.email?.subject}
                      </h2>
                      <div className="text-[13px] text-zbrain-muted mt-1 font-mono">
                        {detail.email?.from}
                        {detail.pipeline?.id && (
                          <span className="text-zbrain-muted/60"> · activity #{detail.pipeline.id}</span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {detail.pipeline?.intent && (
                        <Chip tone="info">{INTENT_LABELS[detail.pipeline.intent] || detail.pipeline.intent}</Chip>
                      )}
                      {detail.pipeline?.autonomy_tier && (
                        <Chip tone={detail.pipeline.autonomy_tier === "L2_HITL" ? "warning" : "info"}>
                          {detail.pipeline.autonomy_tier.replace("_", " ")}
                        </Chip>
                      )}
                    </div>
                  </div>

                  {/* Assignment row */}
                  <div className="mt-3 pt-3 border-t border-zbrain-divider flex items-center gap-3 flex-wrap">
                    <Eyebrow>Assigned to</Eyebrow>
                    <select
                      value={detail.assignee?.user_id || ""}
                      onChange={(e) => handleAssign(detail.id, e.target.value || null)}
                      disabled={assigning}
                      className="text-[12px] bg-zbrain-surface border border-zbrain-divider rounded-md px-2 py-1 outline-none focus:border-zbrain focus:bg-white"
                    >
                      <option value="">(unassigned)</option>
                      {operators.map((u) => (
                        <option key={u.id} value={u.id}>{u.name}</option>
                      ))}
                    </select>
                    {detail.assignee?.assigned_at && (
                      <span className="text-[11px] text-zbrain-muted">
                        since {new Date(detail.assignee.assigned_at).toLocaleString()}
                      </span>
                    )}
                    {detail.owner_queue && (
                      <span className="text-[11px] text-zbrain-muted">
                        queue: <span className="font-medium text-zbrain-ink">{detail.owner_queue}</span>
                      </span>
                    )}
                  </div>
                </Section>
              </Surface>

              {/* Original customer email — the CSR needs this in view while
                  reviewing extracted data and the proposed reply. */}
              {(detail.email?.body || detail.email?.attachments?.length) && (
                <Surface variant="resting">
                  <Section padding="default">
                    <div className="flex items-center justify-between">
                      <Eyebrow>Original customer email</Eyebrow>
                      {detail.email?.attachments && detail.email.attachments.length > 0 && (
                        <span className="text-[11px] text-zbrain-muted">
                          {detail.email.attachments.length} attachment{detail.email.attachments.length === 1 ? "" : "s"}: {detail.email.attachments.join(", ")}
                        </span>
                      )}
                    </div>
                    {detail.email?.body && (
                      <pre className="mt-2 whitespace-pre-wrap text-[12.5px] leading-relaxed text-zbrain-ink bg-zbrain-surface rounded-[10px] p-3 max-h-72 overflow-auto">
                        {detail.email.body}
                      </pre>
                    )}
                  </Section>
                </Surface>
              )}

              {/* Playbook (focal point) */}
              <CsrPlaybookCard detail={detail} />

              {(detail.payload?.reconcile?.issues || []).length > 0 && (
                <MismatchesPanel issues={detail.payload.reconcile.issues} />
              )}

              {/* Extracted data sits above the proposed action so the CSR can
                  verify what we pulled before reviewing what we want to do. */}
              <ExtractedSection
                isPoIntent={isPoIntent}
                extracted={extracted}
                rawJson={rawJson}
                rawMode={rawMode}
                onRawMode={setRawMode}
                onChange={updateExtracted}
                onRawChange={onRawChange}
              />

              <ProposedActionCard
                preview={detail.payload?.preview}
                executionApplied={detail.execution?.applied}
                showRaw={previewRaw}
                onToggleRaw={() => setPreviewRaw((v) => !v)}
                acks={acks}
                onToggleAck={(i) => setAcks((prev) => prev.map((v, idx) => (idx === i ? !v : v)))}
              />

              {/* === v1.1 HITL-REPLY-GATING START === */}
              {showDraftedReply ? (
                <DraftedReplyCard
                  subject={replySubject}
                  body={replyBody}
                  language={detail.reply?.language || detail.pipeline?.language}
                  onSubject={setReplySubject}
                  onBody={setReplyBody}
                  dirty={replyDirty}
                />
              ) : (
                <div className="card px-4 py-3 text-xs text-zbrain-muted dark:text-zbrain-dark-muted">
                  No customer reply for this intent. The action is <strong>redirect / log only</strong>.
                  Review the extracted data above, then approve to record the routing decision (no email
                  leaves the system; DEMO_TRANSMIT_LOCKED).
                </div>
              )}
              {/* === v1.1 HITL-REPLY-GATING END === */}

              {/* CSR note */}
              <Surface variant="resting">
                <Section padding="default">
                  <Eyebrow>CSR note</Eyebrow>
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="Optional context: fed to the continuous-learning loop on resolve"
                    className="w-full mt-2 bg-zbrain-surface border-0 rounded-[10px] px-3 py-2 text-[13px] focus:bg-white focus:shadow-[inset_0_0_0_1px_rgba(26,85,249,0.30)] outline-none transition-all"
                  />
                </Section>
              </Surface>

              {/* Actions */}
              <Surface variant="raised">
                <div className="px-5 py-4 flex items-center gap-2 flex-wrap">
                  {/* === v1.1 HITL-REPLY-GATING START === */}
                  {(() => {
                    const allAcksReady = acks.length === 0 || acks.every(Boolean);
                    const ackTooltip = allAcksReady
                      ? undefined
                      : `Tick every required acknowledgment above before approving. ${acks.filter(Boolean).length} of ${acks.length} ticked.`;
                    return (
                      <>
                        <Button
                          variant="primary"
                          disabled={submitting || !allAcksReady}
                          onClick={() => submit("approve")}
                          title={ackTooltip}
                        >
                          {showDraftedReply
                            ? (replyDirty ? "Send edited reply" : "Approve & send reply")
                            : "Approve & log redirect"}
                        </Button>
                        {showDraftedReply && (
                          <Button
                            variant="secondary"
                            disabled={submitting || !allAcksReady}
                            onClick={() => submit("edit_and_approve")}
                            title={ackTooltip || "Apply your edits to the extracted data and the reply, then approve and send"}
                          >
                            Apply data edits & send
                          </Button>
                        )}
                        <Button variant="rose" disabled={submitting} onClick={() => submit("reject")}>
                          Reject{showDraftedReply ? ": don't send" : ""}
                        </Button>
                      </>
                    );
                  })()}
                  {/* === v1.1 HITL-REPLY-GATING END === */}
                  {detail.pipeline?.id && (
                    <LinkButton variant="ghost" className="ml-auto" onClick={() => navigate(`/trace/${detail.pipeline!.id}`)}>
                      Open in Trace →
                    </LinkButton>
                  )}
                </div>
              </Surface>
            </>
          )}
        </div>
      </div>

      {toast && (
        <div
          className={`fixed bottom-6 right-6 px-4 py-2.5 rounded-[10px] text-[13px] font-medium shadow-elev-3 z-50
            ${toast.kind === "ok" ? "bg-emerald-600 text-white" : "bg-rose-600 text-white"}`}
          style={{ animation: "slideDown 220ms var(--ease-spring)" }}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}

function ProposedActionCard({
  preview,
  executionApplied,
  showRaw,
  onToggleRaw,
  acks,
  onToggleAck,
}: {
  preview: any;
  executionApplied?: any;
  showRaw: boolean;
  onToggleRaw: () => void;
  acks?: boolean[];
  onToggleAck?: (index: number) => void;
}) {
  const action = preview?.action;
  const hasAction = !!action && action !== "-";
  const label = hasAction ? (ACTION_LABELS[action] || action.replaceAll("_", " ")) : "Manual handling: no automation proposed";
  const blurb = hasAction ? (ACTION_BLURBS[action] || "") : "No automated action is mapped for this intent. The CSR resolves manually using the Salesforce playbook below.";
  const ex = preview?.extracted || {};
  const lineCount = Array.isArray(ex.line_items) ? ex.line_items.length : 0;
  const total =
    typeof ex.total === "number"
      ? ex.total
      : (ex.line_items || []).reduce(
          (s: number, li: any) => s + (Number(li?.qty) || 0) * (Number(li?.unit_price) || 0),
          0
        );
  const wos = executionApplied?.work_orders;

  return (
    <Surface variant="resting" className="overflow-hidden">
      <div className="px-5 pt-4 pb-3 flex items-center justify-between">
        <Eyebrow>Proposed action: applied on approve</Eyebrow>
        <button onClick={onToggleRaw} className="text-[11px] text-zbrain hover:underline">
          {showRaw ? "← back to summary" : "show raw JSON"}
        </button>
      </div>
      {showRaw ? (
        <pre className="text-[11px] bg-zbrain-surface mx-5 mb-5 rounded-[10px] p-3 max-h-44 overflow-auto whitespace-pre-wrap">
          {JSON.stringify({ preview, executionApplied }, null, 2)}
        </pre>
      ) : (
        <div className="px-5 pb-5 space-y-2">
          <div className="flex items-center gap-2">
            <Chip tone="emphasis"><span className="font-semibold">{label}</span></Chip>
            {ex.po_number && <span className="font-mono text-[12px] text-zbrain-ink">{ex.po_number}</span>}
            {ex.quote_number && (
              <span className="text-xs text-zbrain-muted">
                · against quote <span className="font-mono">{ex.quote_number}</span>
              </span>
            )}
            {ex.order_number && (
              <span className="text-xs text-zbrain-muted">
                · order <span className="font-mono">{ex.order_number}</span>
              </span>
            )}
          </div>
          {blurb && <div className="text-xs text-zbrain-muted">{blurb}</div>}
          {lineCount > 0 && (
            <div className="text-xs text-zbrain-muted">
              {lineCount} line item{lineCount === 1 ? "" : "s"}
              {total > 0 ? ` · total $${total.toLocaleString(undefined, { minimumFractionDigits: 2 })}` : ""}
              {ex.requested_ship_date ? ` · requested ship ${ex.requested_ship_date}` : ""}
              {ex.payment_terms ? ` · ${ex.payment_terms}` : ""}
            </div>
          )}
          {Array.isArray(wos) && wos.length > 0 && (
            <div className="mt-2">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted mb-1">
                Will report status of {wos.length} work order{wos.length === 1 ? "" : "s"}
              </div>
              <div className="border border-zbrain-divider rounded-md overflow-hidden">
                {wos.map((w: any, i: number) => (
                  <div
                    key={i}
                    className={`grid grid-cols-12 gap-2 px-2 py-1.5 text-xs ${
                      i > 0 ? "border-t border-zbrain-divider" : ""
                    }`}
                  >
                    <div className="col-span-3 font-mono">{w.wo_number}</div>
                    <div className="col-span-3">{w.type}</div>
                    <div className="col-span-3">
                      <span className="pill bg-slate-100 text-slate-700 text-[10px]">{w.status}</span>
                    </div>
                    <div className="col-span-3 text-zbrain-muted">{w.team}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <ActionRequiredBlock data={preview?.action_required} acks={acks} onToggleAck={onToggleAck} />
        </div>
      )}
    </Surface>
  );
}

function ActionRequiredBlock({
  data,
  acks,
  onToggleAck,
}: {
  data?: any;
  acks?: boolean[];
  onToggleAck?: (index: number) => void;
}) {
  if (!data || (!data.summary && !data.next_steps?.length && !data.prefilled_fields)) return null;
  const fields: [string, any][] = Object.entries(data.prefilled_fields || {}).filter(
    ([, v]) => v !== null && v !== undefined && v !== ""
  );
  const steps: string[] = Array.isArray(data.next_steps) ? data.next_steps : [];
  const systems: string[] = Array.isArray(data.downstream_systems) ? data.downstream_systems : [];
  return (
    <div className="mt-3 rounded-[10px] border border-zbrain-divider bg-zbrain-surface/60 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.14em] text-zbrain-muted font-semibold">Action required</span>
        {data.label && <span className="text-[12px] font-medium text-zbrain-ink">{data.label}</span>}
      </div>
      {data.summary && <div className="text-xs text-zbrain-muted">{data.summary}</div>}
      {fields.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {fields.map(([k, v]) => (
            <div key={k} className="text-[11.5px]">
              <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted">{prettyKey(k)}</div>
              <div className="font-medium text-zbrain-ink truncate">{String(v)}</div>
            </div>
          ))}
        </div>
      )}
      {systems.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {systems.map((s) => (
            <span key={s} className="pill text-[10px] bg-indigo-50 text-indigo-700">{s}</span>
          ))}
        </div>
      )}
      {steps.length > 0 && (
        <div className="mt-1">
          <div className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold mb-1">
            CSR acknowledgments (tick each before approving)
          </div>
          <ul className="space-y-1.5">
            {steps.map((s, i) => {
              const checked = !!(acks && acks[i]);
              const interactive = !!onToggleAck;
              return (
                <li key={i} className="flex items-start gap-2 text-[12px] text-zbrain-ink">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!interactive}
                    onChange={() => interactive && onToggleAck && onToggleAck(i)}
                    className="mt-0.5 h-3.5 w-3.5 rounded-sm border-zbrain-divider accent-zbrain cursor-pointer shrink-0"
                    aria-label={`Acknowledge: ${s}`}
                  />
                  <label
                    onClick={() => interactive && onToggleAck && onToggleAck(i)}
                    className={`leading-snug select-none ${interactive ? "cursor-pointer" : ""} ${checked ? "text-zbrain-ink" : "text-zbrain-ink/85"}`}
                  >
                    {s}
                  </label>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function prettyKey(k: string): string {
  return k.replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase());
}

function DraftedReplyCard({
  subject,
  body,
  language,
  onSubject,
  onBody,
  dirty,
}: {
  subject: string;
  body: string;
  language?: string | null;
  onSubject: (s: string) => void;
  onBody: (s: string) => void;
  dirty: boolean;
}) {
  const lang = (language || "").toLowerCase();
  return (
    <Surface variant="resting" className="overflow-hidden">
      <div className="px-5 pt-4 pb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Eyebrow>✉ Drafted customer reply</Eyebrow>
          {language && (
            <Chip tone="emphasis">
              {LANG_FLAGS[lang] || "🌐"} {LANG_NAMES[lang] || language}
            </Chip>
          )}
          {dirty && <Chip tone="warning">edited</Chip>}
        </div>
        <div className="text-[11px] text-zbrain-muted">Edits below will be sent on approve</div>
      </div>
      <div className="px-5 pb-5 space-y-3">
        <div>
          <Eyebrow>Subject</Eyebrow>
          <input
            value={subject}
            onChange={(e) => onSubject(e.target.value)}
            className="w-full mt-1 bg-zbrain-surface border-0 rounded-[10px] px-3 py-2 text-[13px] focus:bg-white focus:shadow-[inset_0_0_0_1px_rgba(26,85,249,0.30)] outline-none transition-all"
          />
        </div>
        <div>
          <Eyebrow>Body</Eyebrow>
          <textarea
            value={body}
            onChange={(e) => onBody(e.target.value)}
            className="w-full mt-1 bg-zbrain-surface border-0 rounded-[10px] px-3 py-2.5 text-[13px] font-sans min-h-[240px] whitespace-pre-wrap focus:bg-white focus:shadow-[inset_0_0_0_1px_rgba(26,85,249,0.30)] outline-none transition-all leading-relaxed"
          />
        </div>
      </div>
    </Surface>
  );
}

function ExtractedSection({
  isPoIntent,
  extracted,
  rawJson,
  rawMode,
  onRawMode,
  onChange,
  onRawChange,
}: {
  isPoIntent: boolean;
  extracted: any;
  rawJson: string;
  rawMode: boolean;
  onRawMode: (v: boolean) => void;
  onChange: (v: any) => void;
  onRawChange: (s: string) => void;
}) {
  if (!extracted || Object.keys(extracted).length === 0) {
    return null;
  }
  return (
    <Surface variant="resting" className="overflow-hidden">
      <div className="px-5 pt-4 pb-3 flex items-center justify-between">
        <Eyebrow>
          Extracted data {rawMode ? "· raw JSON" : isPoIntent ? "· edit before approving" : "· read-only"}
        </Eyebrow>
        <button onClick={() => onRawMode(!rawMode)} className="text-[11px] text-zbrain hover:underline">
          {rawMode ? "← back to form" : "show raw JSON"}
        </button>
      </div>
      <div className="px-5 pb-5">
        {rawMode ? (
          <textarea
            value={rawJson}
            onChange={(e) => onRawChange(e.target.value)}
            className="w-full text-[11px] font-mono bg-zbrain-surface border-0 rounded-[10px] p-3 min-h-[280px] focus:bg-white focus:shadow-[inset_0_0_0_1px_rgba(26,85,249,0.30)] outline-none transition-all"
          />
        ) : isPoIntent ? (
          <ExtractedForm value={extracted} onChange={onChange} />
        ) : (
          <ExtractedReadOnly extracted={extracted} />
        )}
      </div>
    </Surface>
  );
}

function ExtractedReadOnly({ extracted }: { extracted: any }) {
  const entries = Object.entries(extracted || {}).filter(
    ([k, v]) => !k.startsWith("_") && v != null && v !== ""
  );
  if (entries.length === 0) {
    return (
      <div className="text-xs text-zbrain-muted italic">
        No structured fields extracted. Agent relied on the email body and customer history to draft the reply above.
      </div>
    );
  }
  // Split scalars (one-line values) from complex (arrays/objects). Scalars
  // fit in a two-column grid; complex fields get their own full-width row
  // so nested data has room to breathe.
  const scalars: [string, any][] = [];
  const complex: [string, any][] = [];
  for (const [k, v] of entries) {
    if (v != null && (Array.isArray(v) || (typeof v === "object" && v !== null))) {
      complex.push([k, v]);
    } else {
      scalars.push([k, v]);
    }
  }
  return (
    <div className="space-y-3">
      {scalars.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {scalars.map(([k, v]) => (
            <LegacyField key={k} label={k.replaceAll("_", " ")}>
              <div className="text-sm break-words">{String(v)}</div>
            </LegacyField>
          ))}
        </div>
      )}
      {complex.map(([k, v]) => (
        <ComplexFieldBlock key={k} label={k.replaceAll("_", " ")} value={v} />
      ))}
    </div>
  );
}

function ComplexFieldBlock({ label, value }: { label: string; value: any }) {
  const isArrayOfObjects = Array.isArray(value) && value.length > 0 && value.every((v) => v && typeof v === "object" && !Array.isArray(v));
  if (isArrayOfObjects) {
    return (
      <div>
        <div className="text-[10px] uppercase tracking-wider text-zbrain-muted/80 font-medium mb-1.5">
          {label} <span className="text-zbrain-muted/60">({value.length})</span>
        </div>
        <div className="space-y-1.5">
          {value.map((item: any, idx: number) => (
            <div key={idx} className="bg-zbrain-surface border border-zbrain-divider rounded-md p-3">
              <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                {Object.entries(item).map(([k, v]) => (
                  <div key={k} className="text-[12px]">
                    <span className="text-zbrain-muted">{k.replaceAll("_", " ")}: </span>
                    <span className="text-zbrain-ink break-words">
                      {v == null || v === "" ? <em className="text-zbrain-muted/60">empty</em> : typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted/80 font-medium mb-1.5">{label}</div>
      <pre className="text-[12px] bg-zbrain-surface border border-zbrain-divider rounded-md p-3 max-h-80 overflow-auto whitespace-pre-wrap font-mono leading-relaxed">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

function MismatchesPanel({ issues }: { issues: any[] }) {
  return (
    <Surface variant="resting" className="p-5">
      <Eyebrow className="mb-2.5">Mismatches detected ({issues.length})</Eyebrow>
      <div className="space-y-1.5">
        {issues.map((it, i) => {
          const blocking = ["price_mismatch", "qty_mismatch", "sku_not_quoted"].includes(it.kind);
          const cls = blocking
            ? "bg-rose-50 border-rose-200 text-rose-900"
            : "bg-amber-50 border-amber-200 text-amber-900";
          return (
            <div key={i} className={`text-xs rounded-md border ${cls} px-3 py-2`}>
              <div className="flex items-center gap-2">
                <span className="font-semibold">{it.kind.replaceAll("_", " ")}</span>
                {it.sku && <span className="font-mono opacity-80">· {it.sku}</span>}
              </div>
              {it.kind === "price_mismatch" && (
                <div className="mt-1 grid grid-cols-3 gap-2 text-[11px]">
                  <Cell label="Quoted" value={`$${it.quoted_price?.toFixed(2)}`} />
                  <Cell label="PO" value={`$${it.po_price?.toFixed(2)}`} />
                  <Cell
                    label="Δ"
                    value={`${it.po_price - it.quoted_price >= 0 ? "+" : ""}$${(
                      it.po_price - it.quoted_price
                    ).toFixed(2)}`}
                  />
                </div>
              )}
              {it.kind === "qty_mismatch" && (
                <div className="mt-1 grid grid-cols-3 gap-2 text-[11px]">
                  <Cell label="Quoted qty" value={String(it.quoted_qty)} />
                  <Cell label="PO qty" value={String(it.po_qty)} />
                  <Cell
                    label="Δ"
                    value={`${it.po_qty - it.quoted_qty >= 0 ? "+" : ""}${it.po_qty - it.quoted_qty}`}
                  />
                </div>
              )}
              {it.kind === "sku_not_quoted" && (
                <div className="mt-1 text-[11px]">
                  <span className="opacity-80">PO line:</span> {it.po_line?.description}
                </div>
              )}
              {it.kind === "sku_typo" && (
                <div className="mt-1 text-[11px]">
                  <span className="font-mono">{it.po_sku}</span> → likely meant{" "}
                  <span className="font-mono">{it.quoted_sku}</span>
                </div>
              )}
              {it.kind === "missing_quoted_line" && (
                <div className="mt-1 text-[11px]">Quoted SKU is not on the PO.</div>
              )}
            </div>
          );
        })}
      </div>
    </Surface>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/70 rounded px-2 py-1 border border-current/10">
      <div className="text-[10px] uppercase opacity-70">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function ExtractedForm({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const items: any[] = Array.isArray(value?.line_items) ? value.line_items : [];
  const setField = (k: string, v: any) => onChange({ ...value, [k]: v });
  const setLine = (i: number, patch: any) => {
    const next = [...items];
    next[i] = { ...next[i], ...patch };
    onChange({ ...value, line_items: next });
  };
  const removeLine = (i: number) => {
    const next = items.filter((_, idx) => idx !== i);
    onChange({ ...value, line_items: next });
  };
  const addLine = () => {
    const next = [...items, { sku: "", description: "", qty: 1, unit_price: 0 }];
    onChange({ ...value, line_items: next });
  };

  const total = items.reduce((s, li) => s + (Number(li.qty) || 0) * (Number(li.unit_price) || 0), 0);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 p-3 bg-zbrain-surface border border-zbrain-divider rounded-md">
        <LegacyField label="PO Number">
          <input
            value={value?.po_number || ""}
            onChange={(e) => setField("po_number", e.target.value)}
            className="w-full text-sm font-mono bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
        <LegacyField label="Quote Reference">
          <input
            value={value?.quote_number || ""}
            onChange={(e) => setField("quote_number", e.target.value || null)}
            className="w-full text-sm font-mono bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
        <LegacyField label="Customer">
          <input
            value={value?.customer_name || ""}
            onChange={(e) => setField("customer_name", e.target.value)}
            className="w-full text-sm bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
        <LegacyField label="Requested Ship Date">
          <input
            type="date"
            value={value?.requested_ship_date || ""}
            onChange={(e) => setField("requested_ship_date", e.target.value)}
            className="w-full text-sm bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
        <LegacyField label="Payment Terms">
          <input
            value={value?.payment_terms || ""}
            onChange={(e) => setField("payment_terms", e.target.value)}
            className="w-full text-sm bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
        <LegacyField label="Bill To">
          <input
            value={value?.bill_to || ""}
            onChange={(e) => setField("bill_to", e.target.value)}
            className="w-full text-sm bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
        <LegacyField label="Ship To" col2>
          <input
            value={value?.ship_to || ""}
            onChange={(e) => setField("ship_to", e.target.value)}
            className="w-full text-sm bg-white border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </LegacyField>
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs uppercase tracking-wider text-zbrain-muted">Line items ({items.length})</div>
          <button onClick={addLine} className="text-xs text-zbrain hover:underline">
            + add line
          </button>
        </div>
        {items.length === 0 ? (
          <div className="text-xs text-zbrain-muted py-3 text-center border border-dashed border-zbrain-divider rounded">
            No line items extracted.
          </div>
        ) : (
          <div className="border border-zbrain-divider rounded-md overflow-hidden">
            <div className="grid grid-cols-12 gap-2 px-2 py-1.5 bg-zbrain-surface text-[10px] uppercase tracking-wider text-zbrain-muted font-medium">
              <div className="col-span-2">SKU</div>
              <div className="col-span-4">Description</div>
              <div className="col-span-1 text-right">Qty</div>
              <div className="col-span-2 text-right">Unit Price</div>
              <div className="col-span-3 text-right">Ext.</div>
            </div>
            {items.map((li, i) => {
              const ext = (Number(li.qty) || 0) * (Number(li.unit_price) || 0);
              return (
                <div
                  key={i}
                  className="grid grid-cols-12 gap-2 px-2 py-1.5 border-t border-zbrain-divider items-center"
                >
                  <input
                    value={li.sku || ""}
                    onChange={(e) => setLine(i, { sku: e.target.value })}
                    className="col-span-2 text-xs font-mono bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0"
                  />
                  <input
                    value={li.description || ""}
                    onChange={(e) => setLine(i, { description: e.target.value })}
                    title={li.description || ""}
                    className="col-span-4 text-xs bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0"
                  />
                  <input
                    type="number"
                    value={li.qty ?? ""}
                    onChange={(e) => setLine(i, { qty: Number(e.target.value) })}
                    className="col-span-1 text-xs text-right bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0 tabular-nums"
                  />
                  <input
                    type="number"
                    step="0.01"
                    value={li.unit_price ?? ""}
                    onChange={(e) => setLine(i, { unit_price: Number(e.target.value) })}
                    className="col-span-2 text-xs text-right bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0 tabular-nums"
                  />
                  <div className="col-span-3 text-right text-xs tabular-nums flex items-center justify-end gap-1.5 min-w-0">
                    <span className="truncate">${ext.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                    <button
                      onClick={() => removeLine(i)}
                      className="text-zbrain-muted hover:text-rose-600 flex-shrink-0"
                      title="Remove line"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
            <div className="grid grid-cols-12 gap-2 px-2 py-2 border-t border-zbrain-divider bg-zbrain-surface text-xs">
              <div className="col-span-9 text-right text-zbrain-muted">Total</div>
              <div className="col-span-3 text-right font-semibold tabular-nums">
                ${total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>
        )}
      </div>

      {value?.notes && (
        <LegacyField label="Notes">
          <textarea
            value={value.notes}
            onChange={(e) => setField("notes", e.target.value)}
            className="w-full text-sm bg-white border border-zbrain-divider rounded-md px-2 py-1.5 min-h-[60px]"
          />
        </LegacyField>
      )}
    </div>
  );
}

function LegacyField({ label, children, col2 }: { label: string; children: React.ReactNode; col2?: boolean }) {
  return (
    <label className={`block ${col2 ? "col-span-2" : ""}`}>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted mb-0.5">{label}</div>
      {children}
    </label>
  );
}


/** CSR playbook — renders a reason-specific guide explaining what the CSR
 * needs to do AND offering one-click actions (deep links to Salesforce,
 * pipeline re-run, mark-out-of-scope). Branches by `detail.reason`. */
function CsrPlaybookCard({ detail }: { detail: HitlSummary }) {
  const reason = detail.reason || "";
  const cm = detail.customer_match || {};
  const sfBaseUrl = detail.salesforce_instance_url || "";
  const pipelineId = detail.pipeline?.id;
  const ex = detail.payload?.extracted || {};

  const sfLink = (path: string) => (sfBaseUrl ? `${sfBaseUrl}${path.startsWith("/") ? path : "/" + path}` : null);
  const sfNewAccountUrl = (() => {
    if (!sfBaseUrl) return null;
    const customerCode = ex.customer_code || cm.extracted_customer_code_seen || "";
    const customerName = ex.customer_name || cm.extracted_customer_name_seen || "";
    const senderEmail = (cm.extracted_buyer_email_seen || cm.sender_email_seen || "") as string;
    const defaults: string[] = [];
    if (customerName) defaults.push(`Name=${encodeURIComponent(customerName)}`);
    if (customerCode) defaults.push(`Customer_Code__c=${encodeURIComponent(customerCode)}`);
    const qs = defaults.length ? `?defaultFieldValues=${defaults.join(",")}` : "";
    const note = senderEmail ? `&__note=Buyer-email:${encodeURIComponent(senderEmail)}` : "";
    return `${sfBaseUrl}/lightning/o/Account/new${qs}${note}`;
  })();
  const sfSearchUrl = (() => {
    if (!sfBaseUrl) return null;
    const term = ex.customer_name || cm.extracted_customer_name_seen || cm.extracted_customer_code_seen || "";
    if (!term) return `${sfBaseUrl}/lightning/o/Account/list?filterName=__Recent`;
    return `${sfBaseUrl}/lightning/setup/IntegrationProviderManagement/home`.includes("undefined")
      ? null
      : `${sfBaseUrl}/_ui/search/ui/UnifiedSearchResults?str=${encodeURIComponent(term)}`;
  })();
  const sfMatchedAccountUrl = cm.salesforce_account_id ? sfLink(`/lightning/r/Account/${cm.salesforce_account_id}/view`) : null;

  const onRerun = async () => {
    if (!pipelineId) return;
    if (!confirm("Re-run the pipeline from scratch? Use this after you've fixed the issue in Salesforce.")) return;
    await api.retryPipeline(pipelineId);
    alert("Pipeline re-run started. Refresh the HITL queue in a few seconds.");
  };

  // ── Variant 1: customer not found in Salesforce ──────────────────────
  if (reason === "unknown_customer_in_salesforce") {
    const attempts = (cm.attempted_lookups || []) as Array<{ method: string; value: string; matched: boolean }>;
    return (
      <Surface variant="raised" className="overflow-hidden">
        <div className="px-5 py-4 flex items-start gap-3" style={{ background: "linear-gradient(180deg, rgba(245,158,11,0.08) 0%, rgba(245,158,11,0.02) 100%)" }}>
          <div className="w-9 h-9 rounded-[10px] bg-amber-100 text-amber-700 flex items-center justify-center font-semibold text-base shrink-0">!</div>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] font-semibold text-zbrain-ink leading-snug">Customer not in Salesforce</div>
            <div className="text-[13px] text-zbrain-muted mt-1 leading-relaxed">
              The agent couldn't match this email to any Salesforce Account. The pipeline stopped before
              enrichment. Resolve below, then re-run.
            </div>
          </div>
        </div>
        <div className="px-5 pt-4 pb-5 space-y-4">
          <div>
          <Eyebrow>What we tried in Salesforce ({attempts.length} attempt{attempts.length === 1 ? "" : "s"})</Eyebrow>
          <div className="mt-2 bg-zbrain-surface rounded-[10px] divide-y divide-zbrain-divider/40 overflow-hidden">
            {attempts.length === 0 && (
              <div className="px-3 py-2 text-xs text-zbrain-muted italic">no lookup attempts recorded</div>
            )}
            {attempts.map((a, i) => (
              <div key={i} className="px-3 py-2 grid grid-cols-12 gap-2 items-center text-xs">
                <span className="col-span-3 text-zbrain-muted font-mono text-[11px]">{a.method}</span>
                <span className="col-span-7 font-mono truncate" title={a.value}>{a.value || "(empty)"}</span>
                <span className={`col-span-2 text-right pill text-[10px] ${a.matched ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-rose-50 text-rose-700 border border-rose-200"}`}>
                  {a.matched ? "matched" : "no match"}
                </span>
              </div>
            ))}
          </div>

          <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold pt-2">
            What the email said
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <Kv label="Customer name (extracted)" value={ex.customer_name || cm.extracted_customer_name_seen} />
            <Kv label="Customer code (extracted)" value={ex.customer_code || cm.extracted_customer_code_seen} />
            <Kv label="Buyer email (extracted)" value={cm.extracted_buyer_email_seen} />
            <Kv label="Sender email" value={cm.sender_email_seen} />
          </div>

          <div className="pt-3 border-t border-zbrain-divider/40">
            <Eyebrow className="mb-2.5">Resolve in Salesforce</Eyebrow>
            <div className="flex flex-wrap gap-2 mb-4">
              {sfSearchUrl && (
                <LinkButton variant="secondary" href={sfSearchUrl} target="_blank" rel="noreferrer" title="Search Salesforce for an existing Account">
                  🔍 Search in Salesforce
                </LinkButton>
              )}
              {sfNewAccountUrl && (
                <LinkButton variant="primary" href={sfNewAccountUrl} target="_blank" rel="noreferrer" title="Create new Account in Salesforce, prefilled">
                  + Create Account in Salesforce
                </LinkButton>
              )}
              {!sfBaseUrl && (
                <div className="text-[12px] text-rose-700 italic">
                  Salesforce not connected. Connect it in Settings → Integrations to enable deep links.
                </div>
              )}
            </div>
            <Eyebrow className="mb-2.5">After fixing in Salesforce</Eyebrow>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" onClick={onRerun}>↻ Re-run pipeline</Button>
              <Button variant="rose" onClick={() => alert("Marking as out-of-scope: discard pipeline. (Wire to /api/hitl/{id}/discard once endpoint lands.)")}
                title="If this isn't a real Keysight customer (typosquatting / phishing / wrong inbox), discard.">
                Not a Keysight customer
              </Button>
            </div>
          </div>
          </div>
        </div>
      </Surface>
    );
  }

  // ── Variant 2: low confidence — one-click confirmation ───────────────
  if (reason === "low_confidence_one_click") {
    const conf = detail.pipeline?.confidence ?? 0;
    return (
      <Surface variant="raised" className="overflow-hidden">
        <div className="px-5 py-4 flex items-start gap-3" style={{ background: "linear-gradient(180deg, rgba(26,85,249,0.06) 0%, rgba(26,85,249,0.02) 100%)" }}>
          <div className="w-9 h-9 rounded-[10px] bg-zbrain-100 text-zbrain-700 flex items-center justify-center font-semibold text-base shrink-0">⚡</div>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] font-semibold text-zbrain-ink leading-snug">One-click confirmation needed</div>
            <div className="text-[13px] text-zbrain-muted mt-1 leading-relaxed">
              Confidence ({Math.round(conf * 100)}%) is high enough to act, but a soft mismatch or named-account rule
              wants a human glance. Review the proposed action below. If it matches your judgement, click
              <strong className="text-zbrain-ink"> Approve & send reply</strong>.
            </div>
          </div>
        </div>
        <div className="px-5 py-4 text-[13px] text-zbrain-muted space-y-1.5">
          <div>
            <strong className="text-zbrain-ink">Workflow:</strong> read the Proposed Action card → check the
            mismatches panel (if any) → approve, or edit the reply / extracted data and send.
          </div>
          {pipelineId && (
            <div>
              For full agent reasoning, deltas, and per-rule contributions, open{" "}
              <Link className="text-zbrain hover:underline" to={`/trace/${pipelineId}`}>activity #{pipelineId}</Link>.
            </div>
          )}
        </div>
      </Surface>
    );
  }

  // ── Variant 3: low confidence — full review ──────────────────────────
  if (reason === "low_confidence_full_review") {
    return (
      <Surface variant="raised" className="overflow-hidden">
        <div className="px-5 py-4 flex items-start gap-3" style={{ background: "linear-gradient(180deg, rgba(244,63,94,0.06) 0%, rgba(244,63,94,0.02) 100%)" }}>
          <div className="w-9 h-9 rounded-[10px] bg-rose-100 text-rose-700 flex items-center justify-center font-semibold text-base shrink-0">⚠</div>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] font-semibold text-zbrain-ink leading-snug">Full review required</div>
            <div className="text-[13px] text-zbrain-muted mt-1 leading-relaxed">
              Confidence is below the auto-act threshold. Inspect the extracted data for accuracy, verify the
              customer match, and either approve, edit-and-approve, or reject.
            </div>
          </div>
        </div>
        <div className="px-5 py-4 text-[13px] space-y-2">
          <div className="text-zbrain-muted leading-relaxed">
            Common fixes: the LLM mis-extracted a field (edit it below) · the wrong customer matched
            (open in Salesforce + re-run) · the intent looks wrong (reject, then run with manual intent).
          </div>
          {sfMatchedAccountUrl && (
            <div className="pt-1">
              <LinkButton variant="secondary" href={sfMatchedAccountUrl} target="_blank" rel="noreferrer">
                Open matched Account in Salesforce ↗
              </LinkButton>
            </div>
          )}
        </div>
      </Surface>
    );
  }

  // ── Variant 4: spam ──────────────────────────────────────────────────
  if (reason === "spam_discarded") {
    return (
      <Surface variant="resting" className="overflow-hidden">
        <div className="px-5 py-4 flex items-start gap-3 bg-zbrain-surface">
          <div className="w-9 h-9 rounded-[10px] bg-slate-200 text-slate-700 flex items-center justify-center font-semibold text-base shrink-0">✗</div>
          <div className="flex-1 min-w-0">
            <div className="text-[15px] font-semibold text-zbrain-ink leading-snug">Flagged as spam</div>
            <div className="text-[13px] text-zbrain-muted mt-1 leading-relaxed">
              The intake screen classified this as spam / phishing. If you disagree, reject the discard and the
              email will be re-routed to manual triage.
            </div>
          </div>
        </div>
      </Surface>
    );
  }

  // ── Default ──────────────────────────────────────────────────────────
  return (
    <Surface variant="resting" className="overflow-hidden">
      <div className="px-5 py-4 flex items-center gap-3 bg-zbrain-surface">
        <div className="w-9 h-9 rounded-[10px] bg-slate-200 text-slate-700 flex items-center justify-center font-semibold text-base shrink-0">i</div>
        <div className="flex-1 min-w-0">
          <div className="text-[15px] font-semibold text-zbrain-ink">CSR review needed</div>
          <div className="text-[13px] text-zbrain-muted mt-0.5">Reason: <code className="font-mono text-[12px] bg-white px-1.5 py-0.5 rounded">{reason || "unspecified"}</code></div>
        </div>
        {sfMatchedAccountUrl && (
          <LinkButton variant="secondary" href={sfMatchedAccountUrl} target="_blank" rel="noreferrer">
            Open in Salesforce ↗
          </LinkButton>
        )}
      </div>
    </Surface>
  );
}

function Kv({ label, value }: { label: string; value: any }) {
  return (
    <div className="bg-white rounded-[10px] px-3 py-2 border border-zbrain-divider/40">
      <div className="text-[9px] uppercase tracking-[0.10em] text-zbrain-muted font-semibold">{label}</div>
      <div className={`text-[12px] font-mono mt-0.5 ${value ? "text-zbrain-ink" : "text-zbrain-muted/60 italic"}`}>
        {value || "-"}
      </div>
    </div>
  );
}
