import { useEffect, useMemo, useState } from "react";

import { api } from "../api";

type Rule = {
  id: number;
  namespace: string;
  key: string;
  label: string | null;
  description: string | null;
  body: any;
  default_body: any;
  version: number;
  updated_at: string | null;
  updated_by: string | null;
  is_modified: boolean;
};

type Tab =
  | "outlook_rules"
  | "intent"
  | "extract_schema"
  | "business_rules"
  | "translation"
  | "translation_glossary"
  | "spam_heuristic"
  | "language_heuristic"
  | "intent_confidence_rubric"
  | "language_confidence_rubric"
  | "decision_confidence_rubric"
  | "reconcile_checks"
  | "owner_mapping"
  | "pipeline_verification_rules";

type StageTag = {
  /** Display label, e.g. "S1.2" */
  id: string;
  /** Long form, used in tooltips */
  label: string;
  /** Tailwind classes for the pill background+text */
  cls: string;
};

const STAGE_TAGS: Record<string, StageTag> = {
  "S1.0": { id: "S1.0", label: "Stage 1.0: Pre-AI inbox triage (Outlook rules)", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  "S1.2": { id: "S1.2", label: "Stage 1.2: Spam pre-screen", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  "S1.4": { id: "S1.4", label: "Stage 1.4: Language detection", cls: "bg-violet-50 text-violet-700 border-violet-200" },
  "S1.5": { id: "S1.5", label: "Stage 1.5: Inbound translation to English", cls: "bg-slate-100 text-slate-700 border-slate-200" },
  "S5.1": { id: "S5.1", label: "Stage 5.1: Customer reply drafting", cls: "bg-slate-100 text-slate-700 border-slate-200" },
  "S1.7": { id: "S1.7", label: "Stage 1.7: Intent classification", cls: "bg-sky-50 text-sky-700 border-sky-200" },
  "S2.2": { id: "S2.2", label: "Stage 2.2: Schema-driven extraction", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  "S2.5": { id: "S2.5", label: "Stage 2.5: Cross-system validation (reconcile)", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  "S3.1": { id: "S3.1", label: "Stage 3.1: Confidence formula", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  "S3.2": { id: "S3.2", label: "Stage 3.2: Business rules", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  "S5.2": { id: "S5.2", label: "Stage 5.2: Translation", cls: "bg-slate-100 text-slate-700 border-slate-200" },
  "S3.4": { id: "S3.4", label: "Stage 3.4: Assign CCC owner / Pipeline verification", cls: "bg-amber-50 text-amber-700 border-amber-200" },
};

type TabSpec = { key: Tab; label: string; sub: string; stages: string[] };

// Tabs are grouped by their primary pipeline stage so an operator can see
// at a glance "to change Stage 1.4 behavior, edit these two rule sets."
const TABS: TabSpec[] = [
  { key: "outlook_rules", label: "Pre-AI Outlook rules", stages: ["S1.0"], sub: "Six deterministic Outlook-style rules evaluated before any LLM call. Match by subject, sender domain, or body keywords. On match: the email's intent is locked deterministically (confidence 1.0) and the Stage 1 LLM classifier is skipped entirely. Hard-block rules (KSO, Undeliverable) ignore the actionable-exception guard; warn rules suppress themselves when the body also contains a clear business directive so a real order is never dropped." },
  { key: "spam_heuristic", label: "Spam pre-screen rules", stages: ["S1.2"], sub: "Regex/keyword rules from SpamAssassin + SwiftFilter. Runs at sub-step 1.2 before the LLM check." },
  { key: "language_heuristic", label: "Language detection rules", stages: ["S1.4"], sub: "4-tier ruleset (script → diacritic → keyword density → greeting) used as heuristic corroboration in sub-step 1.4." },
  { key: "language_confidence_rubric", label: "Language confidence rubric", stages: ["S1.4"], sub: "Auditable scoring rubric the language detector applies in sub-step 1.4. Tune to shift how cautious the system is on mixed-language or short emails." },
  { key: "intent", label: "Intent definitions", stages: ["S1.7"], sub: "Drives how the intake classifier picks the primary intent." },
  { key: "intent_confidence_rubric", label: "Intent confidence rubric", stages: ["S1.7"], sub: "Auditable scoring rubric the classifier applies to assign sub-step 1.7's intent_confidence number. Tune weights here to shift how fast L4 / L3 / L2 thresholds trigger." },
  { key: "extract_schema", label: "Extraction schemas", stages: ["S2.2"], sub: "Per-intent field lists the document-intelligence agent extracts." },
  { key: "reconcile_checks", label: "Reconcile checks", stages: ["S2.5"], sub: "Cross-system validations the solution runs after extraction. Each check is a predicate against the matched quote, account billing address, recent orders, and similar. 12 default checks cover line items (sku/qty/price), totals, payment terms, currency, addresses, duplicate-PO detection. Operators tune severity (hard/soft/warn) and active flag without touching code." },
  { key: "decision_confidence_rubric", label: "Decision confidence rubric", stages: ["S3.1"], sub: "Auditable Stage 3.1 formula: three weighted signals (intent / extraction / customer_match) and seven floor caps. Operators tune weights and cap thresholds here to shift autonomy-tier behavior without code changes." },
  { key: "business_rules", label: "Business rules", stages: ["S3.2"], sub: "Predicate-driven guardrails that cap confidence or hard-block actions before tier assignment." },
  { key: "translation", label: "Translation rules", stages: ["S1.5", "S5.2"], sub: "Glossary + tone instructions injected into the LLM translator. Used in Stage 1.5 (inbound: customer language → English so downstream stages reason in EN) and Stage 5.2 (outbound: English-drafted reply → customer language). One rule set, two directions; preserve SKUs, currency, units verbatim in both." },
  { key: "translation_glossary", label: "Translation glossary (per language)", stages: ["S1.5", "S5.1", "S5.2"], sub: "Per-language Keysight terminology: one row per concept (calibration certificate, work order, ECCN, and so on) with the canonical translation in every supported customer language. Inbound translator uses it to map customer-language terms to English; the reply drafter uses it to write the customer-language response with the right Keysight phrasing." },
  { key: "owner_mapping", label: "Case ownership", stages: ["S3.4"], sub: "Who owns the CCC Request after Stage 3.4 (the routing key the track classifier emits → human label + Salesforce Queue Id). Drives Case.OwnerId on the Salesforce write. Sync from / provision into Salesforce from Settings → Integrations." },
  { key: "pipeline_verification_rules", label: "Case verification rules", stages: ["S3.4"], sub: "Declarative invariants the verifier evaluates at every stage boundary. Each rule is an applies-when predicate + an invariant predicate + severity + mode. Edit safely in shadow mode and click 'Run against last 200 pipelines' to back-test before promoting to active." },
];

function StageTagPill({ stage, size = "xs" }: { stage: string; size?: "xs" | "sm" }) {
  const meta = STAGE_TAGS[stage];
  if (!meta) return null;
  const sizeCls = size === "sm" ? "text-[11px] px-2 py-0.5" : "text-[10px] px-1.5 py-0.5";
  return (
    <span
      className={`inline-flex items-center font-mono font-semibold rounded border ${sizeCls} ${meta.cls}`}
      title={meta.label}
    >
      {meta.id}
    </span>
  );
}

type Severity = "hard_block" | "cap_at_0.70" | "cap_at_0.88" | "warn";

const SEVERITIES: { key: Severity; label: string; description: string; pill: string }[] = [
  { key: "hard_block",  label: "Hard block",       description: "Refuse the action entirely. The case cannot auto-close or one-click; only manual handling.", pill: "bg-rose-100 text-rose-800 border-rose-200" },
  { key: "cap_at_0.70", label: "Cap → L2 review",  description: "Force the case down to L2 full human review even if the math scored it higher.",              pill: "bg-amber-100 text-amber-800 border-amber-200" },
  { key: "cap_at_0.88", label: "Cap → L3 one-click", description: "Force the case down to L3 one-click approval even if the math scored it higher.",            pill: "bg-yellow-100 text-yellow-800 border-yellow-200" },
  { key: "warn",        label: "Warn only",        description: "Record a trace event for audit; do not change the tier the math chose.",                       pill: "bg-slate-100 text-slate-700 border-slate-200" },
];

const REGION_OPTIONS = ["AMS", "EMEA", "APAC"];

function SeverityPill({ severity }: { severity: string }) {
  const meta = SEVERITIES.find((s) => s.key === severity);
  const cls = meta?.pill || "bg-slate-100 text-slate-700 border-slate-200";
  return (
    <span className={`pill text-[10px] border ${cls}`} title={meta?.description || undefined}>
      {meta?.label || severity}
    </span>
  );
}

async function fetchRules(ns: Tab): Promise<Rule[]> {
  const r = await fetch(`/api/kb/${ns}`);
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

async function saveRule(rule: Rule, body: any, label?: string, description?: string): Promise<Rule> {
  const r = await fetch(`/api/kb/${rule.namespace}/${rule.key}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, label: label ?? rule.label, description: description ?? rule.description }),
  });
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

async function resetRule(rule: Rule): Promise<Rule> {
  const r = await fetch(`/api/kb/${rule.namespace}/${rule.key}/reset`, { method: "POST" });
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

async function createRule(
  namespace: string,
  payload: { key: string; body: any; label?: string; description?: string },
): Promise<Rule> {
  const r = await fetch(`/api/kb/${namespace}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(`${r.status}: ${txt}`);
  }
  return r.json();
}

// Normalize an operator-typed English phrase into a stable rule key. Lowercases,
// replaces spaces and punctuation with underscores, strips parenthetical bits,
// caps length. Used by the glossary editor when an admin adds a new term so
// they do not have to think up a key.
function slugifyKey(english: string): string {
  return english
    .toLowerCase()
    .replace(/\([^)]*\)/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

// Read ?ns=...&key=... once at mount. Deep-links from Trace and Notifications
// land here with the right namespace tab + the failing rule pre-selected so
// the admin doesn't have to scroll through a dozen tabs.
function readDeepLink(): { ns: Tab | null; key: string | null } {
  if (typeof window === "undefined") return { ns: null, key: null };
  const params = new URLSearchParams(window.location.search);
  const ns = params.get("ns");
  const key = params.get("key");
  const validNs = TABS.find((t) => t.key === ns);
  return { ns: validNs ? (ns as Tab) : null, key };
}

export function KnowledgeBasePage() {
  const initial = readDeepLink();
  const [tab, setTab] = useState<Tab>(initial.ns || "intent");
  const [rules, setRules] = useState<Rule[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showAddGlossaryModal, setShowAddGlossaryModal] = useState(false);
  // Honor ?key=... only on the first reload after mount, then clear it so
  // subsequent tab switches go to the first rule as before.
  const [pendingKey, setPendingKey] = useState<string | null>(initial.key);

  const reload = (ns: Tab, preferKey?: string) => {
    fetchRules(ns).then((r) => {
      setRules(r);
      const next = preferKey && r.find((x) => x.key === preferKey) ? preferKey : r[0]?.key ?? null;
      setSelected(next);
    });
  };

  useEffect(() => {
    reload(tab, pendingKey || undefined);
    if (pendingKey) setPendingKey(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const filtered = useMemo(() => {
    const t = search.trim().toLowerCase();
    let list = rules;
    if (t) {
      list = list.filter(
        (r) =>
          r.key.toLowerCase().includes(t) ||
          (r.label || "").toLowerCase().includes(t) ||
          (r.description || "").toLowerCase().includes(t)
      );
    }
    if (tab === "business_rules") {
      list = [...list].sort((a, b) => {
        const pa = (a.body?.priority ?? 999) as number;
        const pb = (b.body?.priority ?? 999) as number;
        if (pa !== pb) return pa - pb;
        return a.key.localeCompare(b.key);
      });
    }
    return list;
  }, [rules, search, tab]);

  const sel = rules.find((r) => r.key === selected) || null;

  const onUpdate = (updated: Rule) => {
    setRules((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
  };

  // Cross-list tabs into EVERY stage they serve (a tab tagged S1.5 + S5.2
  // appears in both Stage 1 and Stage 5 groups). Operators looking for
  // "what drives Stage 5 behavior?" expect the translation tabs to be there
  // even though their primary stage is 1.5.
  const tabsByStage = useMemo(() => {
    const groups: Record<string, TabSpec[]> = {};
    const seenInGroup: Record<string, Set<string>> = {};
    for (const t of TABS) {
      const stageKeys = new Set<string>();
      for (const s of t.stages) {
        stageKeys.add(s.split(".")[0]); // "S1.5" -> "S1", "S5.2" -> "S5"
      }
      for (const sk of stageKeys) {
        groups[sk] = groups[sk] || [];
        seenInGroup[sk] = seenInGroup[sk] || new Set();
        if (!seenInGroup[sk].has(t.key)) {
          seenInGroup[sk].add(t.key);
          groups[sk].push(t);
        }
      }
    }
    return groups;
  }, []);
  const activeTab = TABS.find((t) => t.key === tab);

  const STAGE_GROUP_LABELS: Record<string, string> = {
    S1: "Stage 1: Intake",
    S2: "Stage 2: Extract",
    S3: "Stage 3: Decide",
    S5: "Stage 5: Communicate",
  };

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <div className="card p-4">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div className="min-w-0">
              <h1 className="display-md">Knowledge Base</h1>
              <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">
                Editable rules the agents read at request time. Each rule set is tagged with the
                processing stage that consumes it, so the rules behind any stage's behavior are visible at a glance.
              </p>
            </div>
            {activeTab && (
              <div className="flex items-center gap-2 shrink-0">
                {activeTab.stages.map((s) => (
                  <StageTagPill key={s} stage={s} size="sm" />
                ))}
              </div>
            )}
          </div>

          <div className="space-y-2">
            {Object.entries(tabsByStage).map(([stageKey, specs]) => (
              <div key={stageKey} className="flex items-start gap-3 py-1">
                <div className="shrink-0 w-32 pt-1.5">
                  <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">
                    {STAGE_GROUP_LABELS[stageKey] || stageKey}
                  </div>
                </div>
                <div className="flex items-center gap-1 flex-wrap flex-1">
                  {specs.map((t) => (
                    <button
                      key={t.key}
                      onClick={() => setTab(t.key)}
                      className={`text-xs px-3 py-1.5 rounded-md border transition-colors flex items-center gap-2 ${
                        tab === t.key
                          ? "bg-zbrain text-white border-zbrain"
                          : "bg-white text-zbrain-ink border-zbrain-divider hover:bg-zbrain-50"
                      }`}
                    >
                      <span>{t.label}</span>
                      {t.stages.map((s) => (
                        <span
                          key={s}
                          className={`font-mono font-semibold text-[9px] px-1 py-0.5 rounded ${
                            tab === t.key
                              ? "bg-white/20 text-white"
                              : (STAGE_TAGS[s]?.cls || "bg-slate-100 text-slate-700")
                          }`}
                          title={STAGE_TAGS[s]?.label}
                        >
                          {s}
                        </span>
                      ))}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-zbrain-divider/60 text-xs text-zbrain-muted">
            {activeTab?.sub}
          </div>
        </div>
      </div>

      <div className="col-span-4 card overflow-hidden">
        <div className="p-3 border-b border-zbrain-divider space-y-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search rules…"
            className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
          />
          {tab === "business_rules" && (
            <button
              onClick={() => setShowAddModal(true)}
              className="w-full text-xs btn-secondary"
            >
              + add new rule
            </button>
          )}
          {tab === "translation_glossary" && (
            <button
              onClick={() => setShowAddGlossaryModal(true)}
              className="w-full text-xs btn-secondary"
            >
              + add new glossary term
            </button>
          )}
        </div>
        <div className="divide-y divide-zbrain-divider max-h-[calc(100vh-260px)] overflow-auto">
          {filtered.map((r) => (
            <button
              key={r.id}
              onClick={() => setSelected(r.key)}
              className={`w-full text-left p-3 hover:bg-zbrain-50/50 transition-colors ${
                selected === r.key ? "bg-zbrain-50" : ""
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium truncate flex-1">{r.label || r.key}</span>
                {tab === "business_rules" && r.body?.severity && (
                  <SeverityPill severity={r.body.severity} />
                )}
                {tab === "spam_heuristic" && r.body?.category && (
                  <span className="pill text-[9px] bg-rose-50 text-rose-700 border border-rose-200">
                    {r.body.category}
                  </span>
                )}
                {tab === "language_heuristic" && r.body?.language && (
                  <span className="pill text-[9px] bg-sky-50 text-sky-700 border border-sky-200">
                    {r.body.language}
                  </span>
                )}
                {tab === "language_heuristic" && r.body?.tier != null && (
                  <span className="pill text-[9px] bg-slate-50 text-slate-600 border border-slate-200">
                    T{r.body.tier}
                  </span>
                )}
                {r.is_modified && (
                  <span
                    className="w-2 h-2 rounded-full bg-amber-500 shrink-0"
                    title="edited"
                  />
                )}
              </div>
              <div className="text-[11px] text-zbrain-muted font-mono mt-0.5 truncate">{r.key}</div>
              {r.description && (
                <div className="text-[11px] text-zbrain-muted mt-1 line-clamp-2">{r.description}</div>
              )}
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="p-6 text-center text-sm text-zbrain-muted">No rules match.</div>
          )}
        </div>
      </div>

      <div className="col-span-8">
        {sel ? (
          tab === "intent" ? (
            <IntentEditor rule={sel} onUpdate={onUpdate} />
          ) : tab === "extract_schema" ? (
            <SchemaEditor rule={sel} onUpdate={onUpdate} />
          ) : tab === "business_rules" ? (
            <BusinessRuleEditor rule={sel} onUpdate={onUpdate} />
          ) : (tab === "decision_confidence_rubric" || tab === "intent_confidence_rubric" || tab === "language_confidence_rubric") ? (
            <RubricRuleEditor rule={sel} onUpdate={onUpdate} namespace={tab} />
          ) : tab === "translation_glossary" ? (
            <GlossaryEditor rule={sel} onUpdate={onUpdate} />
          ) : (
            <GenericRuleEditor rule={sel} onUpdate={onUpdate} namespace={tab} />
          )
        ) : (
          <div className="card p-12 text-center text-sm text-zbrain-muted">Select a rule on the left.</div>
        )}
      </div>

      {showAddModal && (
        <AddBusinessRuleModal
          onClose={() => setShowAddModal(false)}
          onCreated={(key) => {
            setShowAddModal(false);
            reload("business_rules", key);
          }}
        />
      )}

      {showAddGlossaryModal && (
        <AddGlossaryModal
          existingKeys={new Set(rules.map((r) => r.key))}
          onClose={() => setShowAddGlossaryModal(false)}
          onCreated={(key) => {
            setShowAddGlossaryModal(false);
            reload("translation_glossary", key);
          }}
        />
      )}
    </div>
  );
}

function RuleHeader({
  rule,
  onSaved,
  onReverted,
  saving,
  setSaving,
  body,
  resetForm,
  formDirty,
  onSave,
}: {
  rule: Rule;
  onSaved: (r: Rule) => void;
  onReverted: () => void;
  saving: boolean;
  setSaving: (b: boolean) => void;
  body: any;
  resetForm: () => void;
  formDirty: boolean;
  onSave: () => Promise<void>;
}) {
  const onReset = async () => {
    if (!confirm(`Reset "${rule.label || rule.key}" to its seeded default? Your edits will be lost.`)) return;
    setSaving(true);
    try {
      const r = await resetRule(rule);
      onSaved(r);
      onReverted();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="px-4 py-3 border-b border-zbrain-divider flex items-start justify-between gap-3">
      <div>
        <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">{rule.namespace}</div>
        <h2 className="text-base font-semibold mt-0.5">{rule.label || rule.key}</h2>
        <div className="text-[11px] font-mono text-zbrain-muted">{rule.key}</div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[10px] text-zbrain-muted">
          v{rule.version} · {rule.updated_at ? new Date(rule.updated_at).toLocaleString() : ""} · by{" "}
          {rule.updated_by || "system"}
        </span>
        {formDirty && (
          <button onClick={resetForm} className="btn-ghost text-xs">
            Discard
          </button>
        )}
        <button onClick={onSave} disabled={saving || !formDirty} className="btn-primary text-xs">
          {saving ? "Saving…" : "Save"}
        </button>
        {rule.is_modified && (
          <button
            onClick={onReset}
            disabled={saving}
            className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
          >
            ↻ Reset to default
          </button>
        )}
      </div>
    </div>
  );
}

function IntentEditor({ rule, onUpdate }: { rule: Rule; onUpdate: (r: Rule) => void }) {
  const initial = rule.body || {};
  const [description, setDescription] = useState<string>(initial.description || "");
  const [trackHint, setTrackHint] = useState<string>(initial.track_hint || "none");
  const [priority, setPriority] = useState<number>(initial.priority ?? 5);
  const [pos, setPos] = useState<string[]>(initial.examples_positive || []);
  const [neg, setNeg] = useState<string[]>(initial.examples_negative || []);
  const [raw, setRaw] = useState<boolean>(false);
  const [rawText, setRawText] = useState<string>(JSON.stringify(initial, null, 2));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next = rule.body || {};
    setDescription(next.description || "");
    setTrackHint(next.track_hint || "none");
    setPriority(next.priority ?? 5);
    setPos(next.examples_positive || []);
    setNeg(next.examples_negative || []);
    setRawText(JSON.stringify(next, null, 2));
    setRaw(false);
  }, [rule.id, rule.version]);

  const buildBody = () => {
    if (raw) {
      return JSON.parse(rawText);
    }
    return {
      description,
      track_hint: trackHint,
      priority,
      examples_positive: pos.filter((s) => s.trim()),
      examples_negative: neg.filter((s) => s.trim()),
    };
  };

  const formDirty = JSON.stringify(buildBody()) !== JSON.stringify(rule.body || {});

  const resetForm = () => {
    const next = rule.body || {};
    setDescription(next.description || "");
    setTrackHint(next.track_hint || "none");
    setPriority(next.priority ?? 5);
    setPos(next.examples_positive || []);
    setNeg(next.examples_negative || []);
    setRawText(JSON.stringify(next, null, 2));
  };

  const onSave = async () => {
    let body: any;
    try {
      body = buildBody();
    } catch (e) {
      alert("Raw JSON is invalid");
      return;
    }
    setSaving(true);
    try {
      const updated = await saveRule(rule, body);
      onUpdate(updated);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <RuleHeader
        rule={rule}
        onSaved={onUpdate}
        onReverted={resetForm}
        saving={saving}
        setSaving={setSaving}
        body={buildBody()}
        resetForm={resetForm}
        formDirty={formDirty}
        onSave={onSave}
      />
      <div className="px-4 py-2 border-b border-zbrain-divider flex items-center justify-end gap-3">
        <button onClick={() => setRaw((v) => !v)} className="text-xs text-zbrain hover:underline">
          {raw ? "← back to form" : "show raw JSON"}
        </button>
      </div>
      {raw ? (
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          className="w-full text-[11px] font-mono p-3 min-h-[420px] focus:outline-none"
        />
      ) : (
        <div className="p-4 space-y-4">
          <FormField label="Description (the prose definition the LLM sees)">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 min-h-[80px] focus:border-zbrain"
            />
          </FormField>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Track hint">
              <select
                value={trackHint}
                onChange={(e) => setTrackHint(e.target.value)}
                className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
              >
                <option value="trade">trade</option>
                <option value="som">som</option>
                <option value="service_contract">service_contract</option>
                <option value="none">none</option>
              </select>
            </FormField>
            <FormField label="Priority (lower = higher precedence on multi-intent)">
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
              />
            </FormField>
          </div>
          <ListEditor
            label="Positive examples (✓ what looks like THIS intent)"
            items={pos}
            onChange={setPos}
            placeholder="e.g. Please find attached our purchase order PO-..."
            tone="emerald"
          />
          <ListEditor
            label="Negative examples (✗ looks similar but is NOT this intent)"
            items={neg}
            onChange={setNeg}
            placeholder="e.g. A fresh PO with no quote_number is po_intake, not quote_to_order"
            tone="rose"
          />
        </div>
      )}
    </div>
  );
}

function SchemaEditor({ rule, onUpdate }: { rule: Rule; onUpdate: (r: Rule) => void }) {
  const initial = rule.body || {};
  const [systemPrompt, setSystemPrompt] = useState<string>(initial.system_prompt || "");
  const [appliesTo, setAppliesTo] = useState<string[]>(initial.applies_to_intents || []);
  const [fields, setFields] = useState<any[]>(initial.fields || []);
  const [raw, setRaw] = useState<boolean>(false);
  const [rawText, setRawText] = useState<string>(JSON.stringify(initial, null, 2));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next = rule.body || {};
    setSystemPrompt(next.system_prompt || "");
    setAppliesTo(next.applies_to_intents || []);
    setFields(next.fields || []);
    setRawText(JSON.stringify(next, null, 2));
    setRaw(false);
  }, [rule.id, rule.version]);

  const buildBody = () => {
    if (raw) return JSON.parse(rawText);
    return {
      system_prompt: systemPrompt,
      applies_to_intents: appliesTo,
      fields: fields.map((f) => ({
        name: f.name || "",
        type: f.type || "string",
        required: !!f.required,
        description: f.description || "",
      })),
    };
  };

  const formDirty = JSON.stringify(buildBody()) !== JSON.stringify(rule.body || {});

  const resetForm = () => {
    const next = rule.body || {};
    setSystemPrompt(next.system_prompt || "");
    setAppliesTo(next.applies_to_intents || []);
    setFields(next.fields || []);
    setRawText(JSON.stringify(next, null, 2));
  };

  const onSave = async () => {
    let body: any;
    try {
      body = buildBody();
    } catch {
      alert("Raw JSON is invalid");
      return;
    }
    setSaving(true);
    try {
      const updated = await saveRule(rule, body);
      onUpdate(updated);
    } finally {
      setSaving(false);
    }
  };

  const addField = () => {
    setFields((f) => [...f, { name: "", type: "string", required: false, description: "" }]);
  };
  const removeField = (i: number) => {
    setFields((f) => f.filter((_, idx) => idx !== i));
  };
  const updateField = (i: number, patch: any) => {
    setFields((f) => {
      const n = [...f];
      n[i] = { ...n[i], ...patch };
      return n;
    });
  };

  return (
    <div className="card overflow-hidden">
      <RuleHeader
        rule={rule}
        onSaved={onUpdate}
        onReverted={resetForm}
        saving={saving}
        setSaving={setSaving}
        body={buildBody()}
        resetForm={resetForm}
        formDirty={formDirty}
        onSave={onSave}
      />
      <div className="px-4 py-2 border-b border-zbrain-divider flex items-center justify-end gap-3">
        <button onClick={() => setRaw((v) => !v)} className="text-xs text-zbrain hover:underline">
          {raw ? "← back to form" : "show raw JSON"}
        </button>
      </div>
      {raw ? (
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          className="w-full text-[11px] font-mono p-3 min-h-[460px] focus:outline-none"
        />
      ) : (
        <div className="p-4 space-y-4">
          <FormField label="Applies to intents">
            <div className="flex flex-wrap gap-1">
              {appliesTo.length === 0 && <span className="text-xs text-zbrain-muted">none</span>}
              {appliesTo.map((i, idx) => (
                <span
                  key={idx}
                  className="pill bg-zbrain-50 text-zbrain text-xs flex items-center gap-1"
                >
                  {i}
                  <button
                    onClick={() => setAppliesTo(appliesTo.filter((_, k) => k !== idx))}
                    className="hover:text-rose-600"
                  >
                    ×
                  </button>
                </span>
              ))}
              <input
                placeholder="add intent + Enter…"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const v = (e.target as HTMLInputElement).value.trim();
                    if (v && !appliesTo.includes(v)) {
                      setAppliesTo([...appliesTo, v]);
                    }
                    (e.target as HTMLInputElement).value = "";
                  }
                }}
                className="text-xs border border-zbrain-divider rounded-md px-2 py-0.5 w-40"
              />
            </div>
          </FormField>
          <FormField label="System prompt (instructions to the extraction agent)">
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 min-h-[100px] focus:border-zbrain"
            />
          </FormField>
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">
                Fields ({fields.length}): what the agent should extract
              </label>
              <button onClick={addField} className="text-xs text-zbrain hover:underline">
                + add field
              </button>
            </div>
            <div className="border border-zbrain-divider rounded-md overflow-hidden">
              <div className="grid grid-cols-12 gap-2 px-2 py-1.5 bg-zbrain-surface text-[10px] uppercase tracking-wider text-zbrain-muted font-medium">
                <div className="col-span-2">Name</div>
                <div className="col-span-2">Type</div>
                <div className="col-span-1 text-center">Req</div>
                <div className="col-span-6">Description</div>
                <div className="col-span-1"></div>
              </div>
              {fields.map((f, i) => (
                <div
                  key={i}
                  className="grid grid-cols-12 gap-2 px-2 py-1.5 border-t border-zbrain-divider items-center"
                >
                  <input
                    value={f.name || ""}
                    onChange={(e) => updateField(i, { name: e.target.value })}
                    placeholder="field_name"
                    className="col-span-2 text-xs font-mono bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0"
                  />
                  <input
                    value={f.type || ""}
                    onChange={(e) => updateField(i, { type: e.target.value })}
                    placeholder="string"
                    className="col-span-2 text-xs font-mono bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0"
                  />
                  <div className="col-span-1 flex items-center justify-center">
                    <input
                      type="checkbox"
                      checked={!!f.required}
                      onChange={(e) => updateField(i, { required: e.target.checked })}
                    />
                  </div>
                  <input
                    value={f.description || ""}
                    onChange={(e) => updateField(i, { description: e.target.value })}
                    placeholder="What this field means"
                    className="col-span-6 text-xs bg-white border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1.5 py-1 min-w-0"
                  />
                  <button
                    onClick={() => removeField(i)}
                    className="col-span-1 text-zbrain-muted hover:text-rose-600 text-xs"
                  >
                    ✕
                  </button>
                </div>
              ))}
              {fields.length === 0 && (
                <div className="px-3 py-6 text-center text-xs text-zbrain-muted">
                  No fields defined. Click "+ add field" to start.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ListEditor({
  label,
  items,
  onChange,
  placeholder,
  tone,
}: {
  label: string;
  items: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  tone: "emerald" | "rose";
}) {
  const ringCls = tone === "emerald" ? "border-emerald-200 bg-emerald-50/30" : "border-rose-200 bg-rose-50/30";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">{label}</div>
      <div className="space-y-1.5">
        {items.map((s, i) => (
          <div key={i} className="flex gap-2">
            <textarea
              value={s}
              onChange={(e) => {
                const n = [...items];
                n[i] = e.target.value;
                onChange(n);
              }}
              className={`flex-1 text-xs border ${ringCls} rounded-md px-2 py-1.5 min-h-[42px]`}
            />
            <button
              onClick={() => onChange(items.filter((_, k) => k !== i))}
              className="text-zbrain-muted hover:text-rose-600 px-1"
              title="Remove"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          onClick={() => onChange([...items, ""])}
          className="text-xs text-zbrain hover:underline"
        >
          + add example
        </button>
        {items.length === 0 && <div className="text-xs text-zbrain-muted italic">{placeholder}</div>}
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold mb-1">{label}</div>
      {children}
    </label>
  );
}

function PillMultiSelect({
  values,
  onChange,
  placeholder,
  suggestions,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  suggestions?: string[];
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {values.length === 0 && <span className="text-xs text-zbrain-muted">none</span>}
      {values.map((i, idx) => (
        <span key={idx} className="pill bg-zbrain-50 text-zbrain text-xs flex items-center gap-1">
          {i}
          <button onClick={() => onChange(values.filter((_, k) => k !== idx))} className="hover:text-rose-600">
            ×
          </button>
        </span>
      ))}
      <input
        placeholder={placeholder}
        list={suggestions ? `pms-${placeholder}` : undefined}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            const v = (e.target as HTMLInputElement).value.trim();
            if (v && !values.includes(v)) onChange([...values, v]);
            (e.target as HTMLInputElement).value = "";
          }
        }}
        className="text-xs border border-zbrain-divider rounded-md px-2 py-0.5 w-40"
      />
      {suggestions && (
        <datalist id={`pms-${placeholder}`}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
    </div>
  );
}

function BusinessRuleEditor({ rule, onUpdate }: { rule: Rule; onUpdate: (r: Rule) => void }) {
  const initial = rule.body || {};
  const [predicate, setPredicate] = useState<string>(initial.predicate || "");
  const [severity, setSeverity] = useState<Severity>((initial.severity as Severity) || "warn");
  const [message, setMessage] = useState<string>(initial.message || "");
  const [appliesTo, setAppliesTo] = useState<string[]>(initial.applies_to_intents || []);
  const [region, setRegion] = useState<string[]>(initial.region || []);
  const [priority, setPriority] = useState<number>(initial.priority ?? 50);
  const [active, setActive] = useState<boolean>(initial.active ?? true);
  const [label, setLabel] = useState<string>(rule.label || "");
  const [raw, setRaw] = useState<boolean>(false);
  const [rawText, setRawText] = useState<string>(JSON.stringify(initial, null, 2));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const next = rule.body || {};
    setPredicate(next.predicate || "");
    setSeverity((next.severity as Severity) || "warn");
    setMessage(next.message || "");
    setAppliesTo(next.applies_to_intents || []);
    setRegion(next.region || []);
    setPriority(next.priority ?? 50);
    setActive(next.active ?? true);
    setLabel(rule.label || "");
    setRawText(JSON.stringify(next, null, 2));
    setRaw(false);
  }, [rule.id, rule.version]);

  const buildBody = () => {
    if (raw) return JSON.parse(rawText);
    return {
      predicate,
      severity,
      message,
      applies_to_intents: appliesTo,
      region,
      priority,
      active,
    };
  };

  const formDirty =
    JSON.stringify(buildBody()) !== JSON.stringify(rule.body || {}) || label !== (rule.label || "");

  const resetForm = () => {
    const next = rule.body || {};
    setPredicate(next.predicate || "");
    setSeverity((next.severity as Severity) || "warn");
    setMessage(next.message || "");
    setAppliesTo(next.applies_to_intents || []);
    setRegion(next.region || []);
    setPriority(next.priority ?? 50);
    setActive(next.active ?? true);
    setLabel(rule.label || "");
    setRawText(JSON.stringify(next, null, 2));
  };

  const validatePredicate = (p: string): string | null => {
    const trimmed = p.trim();
    if (!trimmed) return "Predicate cannot be empty.";
    const ops = ["==", "!=", "<=", ">=", "<", ">", " in ", " not in ", " and ", " or ", " not "];
    if (!ops.some((op) => trimmed.includes(op))) {
      return "Predicate must contain at least one operator (==, <, in, and, …).";
    }
    return null;
  };

  const onSave = async () => {
    let body: any;
    try {
      body = buildBody();
    } catch {
      alert("Raw JSON is invalid");
      return;
    }
    const err = validatePredicate(body.predicate || "");
    if (err) {
      alert(err);
      return;
    }
    setSaving(true);
    try {
      const updated = await saveRule(rule, body, label);
      onUpdate(updated);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-3 border-b border-zbrain-divider flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">{rule.namespace}</div>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="text-base font-semibold mt-0.5 w-full bg-transparent border border-transparent hover:border-zbrain-divider focus:border-zbrain rounded px-1 py-0.5"
          />
          <div className="text-[11px] font-mono text-zbrain-muted mt-0.5">{rule.key}</div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-zbrain-muted">
            v{rule.version} · {rule.updated_at ? new Date(rule.updated_at).toLocaleString() : ""} · by{" "}
            {rule.updated_by || "system"}
          </span>
          {formDirty && (
            <button onClick={resetForm} className="btn-ghost text-xs">
              Discard
            </button>
          )}
          <button onClick={onSave} disabled={saving || !formDirty} className="btn-primary text-xs">
            {saving ? "Saving…" : "Save"}
          </button>
          {rule.is_modified && (
            <button
              onClick={async () => {
                if (!confirm(`Reset "${rule.label || rule.key}" to its seeded default? Your edits will be lost.`)) return;
                setSaving(true);
                try {
                  const r = await resetRule(rule);
                  onUpdate(r);
                  resetForm();
                } finally {
                  setSaving(false);
                }
              }}
              disabled={saving}
              className="btn-secondary text-xs text-rose-700 border-rose-200 hover:bg-rose-50"
            >
              ↻ Reset to default
            </button>
          )}
        </div>
      </div>
      <div className="px-4 py-2 border-b border-zbrain-divider flex items-center justify-end gap-3">
        <button onClick={() => setRaw((v) => !v)} className="text-xs text-zbrain hover:underline">
          {raw ? "← back to form" : "show raw JSON"}
        </button>
      </div>
      {raw ? (
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          className="w-full text-[11px] font-mono p-3 min-h-[460px] focus:outline-none"
        />
      ) : (
        <div className="p-4 space-y-4">
          <FormField label="Predicate (Python-like expression evaluated by the BusinessRulesEvalTool)">
            <textarea
              value={predicate}
              onChange={(e) => setPredicate(e.target.value)}
              spellCheck={false}
              placeholder="e.g. total > 500000"
              className="w-full text-xs font-mono border border-zbrain-divider rounded-md px-3 py-2 min-h-[72px] focus:border-zbrain"
            />
          </FormField>
          <div className="rounded-md border border-zbrain-divider bg-zbrain-surface px-3 py-2 text-[11px] text-zbrain-muted space-y-1">
            <div>
              <span className="font-semibold text-zbrain-ink">Variables:</span>{" "}
              <code className="font-mono">total</code>, <code className="font-mono">intent</code>,{" "}
              <code className="font-mono">customer_code</code>, <code className="font-mono">compliance</code> (list of strings),{" "}
              <code className="font-mono">payment_terms</code>, <code className="font-mono">region</code>,{" "}
              <code className="font-mono">discount_pct</code>, <code className="font-mono">any_eol_sku</code>
            </div>
            <div>
              <span className="font-semibold text-zbrain-ink">Operators:</span>{" "}
              <code className="font-mono">==</code> <code className="font-mono">!=</code> <code className="font-mono">{"<"}</code>{" "}
              <code className="font-mono">{"<="}</code> <code className="font-mono">{">"}</code>{" "}
              <code className="font-mono">{">="}</code> <code className="font-mono">in</code>{" "}
              <code className="font-mono">not in</code> <code className="font-mono">and</code>{" "}
              <code className="font-mono">or</code> <code className="font-mono">not</code>
            </div>
            <div>
              <span className="font-semibold text-zbrain-ink">Examples:</span>{" "}
              <code className="font-mono">total &gt; 500000</code> ·{" "}
              <code className="font-mono">'ITAR' in compliance</code> ·{" "}
              <code className="font-mono">payment_terms not in ['Net 30','Net 45','Net 60']</code>
            </div>
          </div>

          <FormField label="Severity (what the runtime does when this predicate is true)">
            <div className="grid grid-cols-1 gap-1.5">
              {SEVERITIES.map((s) => (
                <label
                  key={s.key}
                  className={`flex items-start gap-2 border rounded-md px-3 py-2 cursor-pointer transition-colors ${
                    severity === s.key ? "border-zbrain bg-zbrain-50/40" : "border-zbrain-divider hover:bg-zbrain-50/30"
                  }`}
                >
                  <input
                    type="radio"
                    name="severity"
                    value={s.key}
                    checked={severity === s.key}
                    onChange={() => setSeverity(s.key)}
                    className="mt-0.5"
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <SeverityPill severity={s.key} />
                      <span className="text-xs text-zbrain-muted">{s.description}</span>
                    </div>
                  </div>
                </label>
              ))}
            </div>
          </FormField>

          <FormField label="Message (shown to the CSR when this rule fires)">
            <input
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 focus:border-zbrain"
            />
          </FormField>

          <FormField label="Applies to intents">
            <PillMultiSelect values={appliesTo} onChange={setAppliesTo} placeholder="add intent + Enter…" />
          </FormField>

          <FormField label="Region (empty = all regions)">
            <PillMultiSelect
              values={region}
              onChange={setRegion}
              placeholder="add region + Enter…"
              suggestions={REGION_OPTIONS}
            />
          </FormField>

          <div className="grid grid-cols-2 gap-4">
            <FormField label="Priority (0–100, lower fires first)">
              <input
                type="number"
                min={0}
                max={100}
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
              />
            </FormField>
            <FormField label="Active">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
                <span>{active ? "rule is active" : "rule is disabled"}</span>
              </label>
            </FormField>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Plain-English explainer registry. One entry per Tab namespace. Used by the
// NamespaceExplainer component below to replace the dense paragraph-style
// help text with a scannable, sectioned panel: WHAT this is, WHEN it fires
// in the pipeline, the FIELDS in plain English, and HOW TO TUNE it safely.
// Functional users do not need to read JSON to understand a rule any more.
// ============================================================================

type KbExplainer = {
  what: string;                                 // One sentence describing what this rule set controls.
  when: string;                                 // When in the pipeline these rules fire.
  fields: { name: string; meaning: string }[];  // Per-field plain-English meanings.
  how_to_tune: string[];                        // Concrete tuning levers a CSR can pull.
  example?: string;                             // A short worked example, optional.
};

const KB_EXPLAINERS: Partial<Record<Tab, KbExplainer>> = {
  outlook_rules: {
    what: "Six deterministic rules that triage inbound email at Stage 1.0, before any LLM call. Mirrors the prior Keysight POC's Outlook inbox rules, now stored in the KB so operators can tune them without a code change.",
    when: "Evaluated once per email, in priority order, immediately after IMAP ingestion. The first rule that matches assigns the intent deterministically (intent_confidence = 1.0) and the Stage 1 LLM classifier is skipped entirely. If no rule matches, the email falls through to the Stage 1 LLM.",
    fields: [
      { name: "priority", meaning: "Lower number is checked first. First match wins; no rule cascade." },
      { name: "enabled", meaning: "Off-switch. Set to false to disable a rule without deleting it (preserves history and the rule body for later re-enable)." },
      { name: "intent", meaning: "Canonical intent label assigned on match. Drives downstream funnel routing. Vocabulary includes: undeliverable, out_of_scope, brazil_tax, kso, collections, portal_admin." },
      { name: "severity", meaning: "hard_block ends the pipeline immediately at the redirect (no further LLM work, ever). warn redirects but still logs telemetry. KSO + Undeliverable are hard_block; the other four are warn." },
      { name: "redirect_to", meaning: "Destination mailbox the rule routes to. null means discard entirely (used for bounces). Examples: keysightorders@keysight.com (KSO), collections.pdl-americas@keysight.com, portal-admin.pdl-ccc-americas@keysight.com." },
      { name: "actionable_exception", meaning: "Safety guard. When true and the body also contains a clear business directive (please, kindly, ship, cancel, update, process, release, schedule, expedite, find attached, requesting), the rule is SUPPRESSED and the email falls through to the LLM. Prevents a real order from being dropped when it happens to mention an OOO-like phrase. Hard-block rules ignore this guard by design (KSO export-control cannot tolerate a heuristic miss)." },
      { name: "predicates", meaning: "OR'd list of conditions. Each predicate has a kind and a value array. Kinds: subject_contains, subject_equals, body_contains, sender_equals, sender_contains, sender_domain, regex_subject, regex_body. Any one predicate matching means the rule matches." },
    ],
    how_to_tune: [
      "If a known defense prime is leaking past the KSO rule (you see the email classified as something else but it should have routed to keysightorders@keysight.com), add the sender's domain to outlook.kso predicates.kind=sender_domain. The rule fires on next poll.",
      "If a Collections-team email is being misrouted to the AI pipeline, capture the recurring subject pattern and add it to outlook.collections predicates.kind=subject_contains.",
      "If a rule is too aggressive (e.g., catching real customer orders that mention OOO), confirm actionable_exception=true on that rule so a directive-bearing body falls through to the LLM. Never set actionable_exception=true on KSO or Undeliverable.",
      "To temporarily disable a rule during an incident (e.g., Brazil tax forwarder address changed), set enabled=false. To delete a rule entirely, remove it from the seed file; the DB row stays until cleaned manually so audits keep the history.",
      "Priorities are stepped at 10, 20, 30, 40, 50, 60. Leave gaps so you can insert a new rule between two existing ones without renumbering.",
    ],
    example:
      "An email arrives from 'security.alerts@lmco.com' with body 'Please ship 10x N5193A by Friday'. The outlook.kso rule fires (sender_domain=lmco.com + body_contains=N5193A). severity=hard_block, so actionable_exception is ignored. Intent locks to 'kso', confidence=1.0, the email is redirected to keysightorders@keysight.com and the pipeline ends. No LLM call. No SOA. No Salesforce write. The audit trail records the rule key, the matched predicate, and the redirect.",
  },
  decision_confidence_rubric: {
    what: "The math the system uses at Stage 3 to assign a final confidence number (0.00 – 1.00) to every case. The number decides whether the case closes automatically (L4), needs a one-click human approval (L3), or goes to full human review (L2).",
    when: "Runs once per case after extraction completes, before the tier and owner are stamped on the Salesforce Case.",
    fields: [
      { name: "kind = base", meaning: "The starting prior every case begins from before any signal is added. Today's base is 0.00." },
      { name: "kind = weighted_signal", meaning: "Adds (weight × signal) to the running total. The three default signals are intent confidence (how sure the classifier was about the intent), extraction completeness (how many required fields the document yielded), and customer match score (how confidently the sender was tied to a real Salesforce account)." },
      { name: "kind = floor_cap", meaning: "Forces the confidence DOWN to a ceiling when its predicate is true. Used to keep risky cases out of L4 even if the math otherwise scores them high." },
      { name: "weight", meaning: "How much of that signal counts toward the score. 0.45 means 45%. The three default weights sum to 1.0." },
      { name: "signal_var", meaning: "Which Stage-1/Stage-2 number to use. One of: intent_confidence, extraction_completeness, customer_match_score." },
      { name: "cap", meaning: "The maximum confidence the case can carry after this rule fires. 0.85 forces L3 one-click. 0.70 forces L2 review." },
      { name: "predicate", meaning: "A boolean expression that decides whether this floor_cap applies. Example: \"customer_match_score < 0.95\" caps confidence on any fuzzy-name match." },
      { name: "active", meaning: "Off-switch. Set to false to disable the rule without deleting it." },
    ],
    how_to_tune: [
      "To make the system trust intent classification more, raise the weight on intent_confidence and lower the others (keep the three weights summing to ~1.0).",
      "To keep cases with fuzzy customer matches out of L4, lower the cap on the customer-match floor (e.g., 0.85 → 0.75).",
      "To add a new policy ceiling (\"orders over $500k never close autonomously\"), add a new floor_cap rule with predicate \"total > 500000\" and cap 0.70.",
      "If a rule is too aggressive, set active=false to switch it off rather than deleting it (preserves history).",
    ],
    example:
      "A case has intent_confidence=0.95, extraction_completeness=0.90, customer_match_score=0.80. The score is (0.45 × 0.95) + (0.35 × 0.90) + (0.20 × 0.80) = 0.90. Then a floor_cap fires because customer_match_score < 0.95, capping the result at 0.85. Final tier: L3 one-click.",
  },
  intent_confidence_rubric: {
    what: "How confident the system is that it picked the correct intent for an inbound email (PO intake, quote-to-order, service contract, etc.). The number controls how the case is routed at Decide.",
    when: "Runs at sub-step 1.7 of intake, after the classifier picks an intent. The LLM evaluates every rule below and reports matched + delta + evidence; the server recomputes the final number.",
    fields: [
      { name: "kind = base", meaning: "The starting prior on every intent classification. Today's base is 0.50 (the classifier needs evidence on both sides to move from this neutral floor)." },
      { name: "kind = trigger", meaning: "A piece of evidence that pushes confidence UP when present (e.g., the subject contains \"PO\" or \"Convert quote\")." },
      { name: "kind = clearance", meaning: "Reward for an unambiguous case with no contradictory signals. Smaller positive contribution than triggers." },
      { name: "kind = penalty", meaning: "A piece of evidence that pulls confidence DOWN when present (e.g., the email body contradicts the subject)." },
      { name: "default_delta", meaning: "How much this rule moves the score when it matches. Positive for triggers/clearances, negative for penalties." },
      { name: "per_intent_overrides", meaning: "Per-intent tweaks. If \"po_intake\" needs a stronger boost than \"general_inquiry\" for the same rule, override here." },
      { name: "examples", meaning: "Short phrases the LLM uses to recognise this signal. The more concrete the example, the better the recall." },
    ],
    how_to_tune: [
      "If the classifier is under-confident on po_intake despite obvious PO numbers in the subject, raise the per_intent_override for the subject_explicit_signal rule on po_intake.",
      "If a rule is firing too often (false positives), lower its default_delta.",
      "Add a new clearance rule when you see a clean pattern the classifier is missing (e.g., \"sender domain matches the customer's known billing domain\").",
      "Use active=false to disable a rule without deleting it.",
    ],
  },
  language_confidence_rubric: {
    what: "How confident the system is that it detected the right customer language (English, Spanish, Japanese, or other). Affects whether the system attempts to draft a reply in the customer's language or routes for translation.",
    when: "Runs at sub-step 1.4 of intake, alongside the heuristic language detector.",
    fields: [
      { name: "kind = base", meaning: "Starting prior (0.50). Today's base assumes the classifier needs supporting evidence." },
      { name: "kind = trigger", meaning: "Positive evidence (Japanese script, Spanish diacritics, English keyword density)." },
      { name: "kind = penalty", meaning: "Negative evidence (mixed-language email, very short body, conflicting signals)." },
      { name: "default_delta", meaning: "How much this rule moves the score (positive for triggers, negative for penalties)." },
      { name: "per_language_overrides", meaning: "Per-language tweak (e.g., the script-definitive trigger may matter more for Japanese than for Spanish)." },
    ],
    how_to_tune: [
      "If short Japanese emails are getting routed to HITL because the system is under-confident, raise the per_language_override for script_definitive_match on \"ja\".",
      "If too many mixed-language emails are dropping confidence too far, lower the mixed_language_penalty default_delta.",
      "Use active=false to disable rules that are hurting accuracy in your real-world traffic.",
    ],
  },
  business_rules: {
    what: "Plain-English business policies that cap or block the system's autonomy before it acts. Each rule is a boolean predicate plus a severity that says what to do if the predicate is true.",
    when: "Runs at sub-step 3.2 of Decide, after the confidence rubric and before the final tier is assigned.",
    fields: [
      { name: "predicate", meaning: "A boolean expression evaluated on the case. Example: \"total > 500000\" or \"'ITAR' in compliance\". When the expression is true, the severity below is applied." },
      { name: "severity = hard_block", meaning: "Refuse the action entirely. The case cannot be auto-closed or one-clicked; only manual handling." },
      { name: "severity = cap_at_0.70", meaning: "Force the tier down to L2 human review even if confidence was high." },
      { name: "severity = cap_at_0.88", meaning: "Force the tier down to L3 one-click approval even if confidence was high." },
      { name: "severity = warn", meaning: "Trace event only. The case continues at whatever tier the math chose; the warning is recorded for audit but does not block." },
      { name: "message", meaning: "The text shown to the CSR explaining why the rule fired. Should name the policy in plain language." },
      { name: "applies_to_intents", meaning: "Which intents this rule scopes to. Empty list = applies to every intent." },
      { name: "region", meaning: "Which regions this rule scopes to (AMS / EMEA / APAC). Empty = global." },
      { name: "priority", meaning: "Order rules fire in. Lower numbers fire first. Default 50." },
      { name: "active", meaning: "Off-switch. Set to false to disable without deleting." },
    ],
    how_to_tune: [
      "Add a new rule when a policy changes (e.g., \"any order > $1M needs CFO sign-off\" → predicate \"total > 1000000\", severity \"hard_block\").",
      "Loosen a rule by raising the predicate threshold (e.g., total > 500000 → total > 750000).",
      "Tighten by lowering the threshold or raising the severity (warn → cap_at_0.88 → cap_at_0.70 → hard_block).",
      "Use active=false to switch off a rule for a holiday period (e.g., \"discount > 30%\" check during a sale).",
    ],
    example:
      "A PO arrives for $620,000. predicate \"total > 500000\" is true. severity cap_at_0.88 forces the case to L3 one-click. A human approves in one click; the order writes to Salesforce.",
  },
  intent: {
    what: "The list of intent labels the classifier can pick from for every inbound email, plus the description and examples each label is anchored to.",
    when: "Runs at sub-step 1.7 of intake. The classifier picks ONE intent for the email; downstream stages route by that intent.",
    fields: [
      { name: "description", meaning: "Plain-English definition of when this intent applies. Used by the LLM to decide." },
      { name: "track_hint", meaning: "Which downstream track owns this intent: trade, som, service_contract, or none." },
      { name: "priority", meaning: "Tie-breaker when two intents look equally likely. Lower fires first." },
      { name: "examples_positive", meaning: "Short phrases that mean \"this intent applies\". The classifier learns from these." },
      { name: "examples_negative", meaning: "Short phrases that look related but should NOT be this intent." },
    ],
    how_to_tune: [
      "When CSRs systematically reclassify an intent, add the corrected phrases to examples_positive on the target intent.",
      "When the classifier is over-eager on an intent, add the false-positive phrases to examples_negative.",
      "Adjust priority to break ties (lower = wins).",
    ],
  },
  spam_heuristic: {
    what: "Deterministic regex/keyword rules that score every inbound email for spam likelihood before the LLM ever sees it.",
    when: "Runs at sub-step 1.2 of intake. Total score across matched rules is compared to a threshold (3.0); above threshold, the email is dropped into the discarded bucket.",
    fields: [
      { name: "category", meaning: "Which kind of spam signal this rule checks (phishing, promotional, automated, etc.). Used to group rules in the trace." },
      { name: "pattern", meaning: "The regex that matches the email subject/body. Use case-insensitive matches and word boundaries to avoid over-matching." },
      { name: "score_weight", meaning: "How much this rule contributes to the spam total when it matches. Higher = stronger spam signal." },
    ],
    how_to_tune: [
      "If a known marketing domain is leaking through, add a new rule with the sender pattern and a weight of ~2.0.",
      "If a rule is over-firing on legitimate emails, lower its score_weight or refine the regex.",
      "Set active=false to disable a rule that is no longer relevant.",
    ],
  },
};

// Lightweight summarizer for rubric rules. Given a parsed rule body, returns
// a one-sentence plain-English description of what THIS specific rule does.
function summarizeRubricRule(body: any): string {
  if (!body || typeof body !== "object") return "";
  const kind = body.kind;
  if (kind === "base") return `Starting prior of ${body.value ?? "?"} (every case begins here).`;
  if (kind === "weighted_signal") {
    const pct = Math.round((Number(body.weight) || 0) * 100);
    return `Adds ${pct}% of the “${body.signal_var || "?"}” score to the running total.`;
  }
  if (kind === "floor_cap") {
    return `When ${body.predicate || "(no predicate)"}, force confidence DOWN to ${body.cap ?? "?"} (ceiling).`;
  }
  if (kind === "trigger") {
    return `When matched, adds ${body.default_delta ?? "?"} to the score. Per-intent overrides: ${
      body.per_intent_overrides && Object.keys(body.per_intent_overrides).length
        ? Object.entries(body.per_intent_overrides).map(([k, v]) => `${k} ${v}`).join(", ")
        : "(none)"
    }.`;
  }
  if (kind === "clearance") return `Reward for an unambiguous case: ${body.default_delta ?? "?"}.`;
  if (kind === "penalty")   return `When matched, subtracts ${Math.abs(Number(body.default_delta) || 0)} from the score.`;
  return "";
}

function NamespaceExplainer({ namespace }: { namespace: Tab }) {
  const ex = KB_EXPLAINERS[namespace];
  if (!ex) return null;
  return (
    <div className="px-4 py-3 border-b border-zbrain-divider bg-zbrain-surface/60">
      <div className="text-sm text-zbrain-ink leading-snug font-medium">{ex.what}</div>
      <div className="text-xs text-zbrain-muted leading-snug mt-1">
        <span className="font-semibold uppercase tracking-wider text-[10px] text-zbrain-muted/80">When it runs: </span>
        {ex.when}
      </div>
      <details className="mt-2 group">
        <summary className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold cursor-pointer hover:text-zbrain-ink select-none">
          What each field means
        </summary>
        <div className="mt-1.5 grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-1 pl-3 border-l-2 border-zbrain-divider/70 text-[12px]">
          {ex.fields.map((f, i) => (
            <div key={i} className="leading-snug">
              <span className="font-mono text-zbrain-muted">{f.name}</span>{": "}
              <span className="text-zbrain-ink/85">{f.meaning}</span>
            </div>
          ))}
        </div>
      </details>
      <details className="mt-1.5">
        <summary className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold cursor-pointer hover:text-zbrain-ink select-none">
          How to tune safely
        </summary>
        <ul className="mt-1.5 pl-5 list-disc text-[12px] text-zbrain-ink/85 leading-snug space-y-0.5">
          {ex.how_to_tune.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
        {ex.example && (
          <div className="mt-1.5 text-[12px] text-zbrain-muted italic pl-5">Example: {ex.example}</div>
        )}
      </details>
    </div>
  );
}

// ============================================================================
// Rubric form editor — one component for decision / intent / language
// confidence rubrics. Dispatches on body.kind and renders a per-kind form so
// operators never touch JSON. A local "Show raw JSON" toggle (default off)
// exposes the underlying JSON for rule owners who want to hand-edit.
// ============================================================================

const KNOWN_INTENTS = [
  "po_intake", "quote_to_order", "service_contract_request",
  "trade_change_order", "wo_update_request", "wo_status_inquiry",
  "service_order", "hold_release", "ssd_change_request",
  "delivery_change", "general_inquiry", "kso", "collections",
  "portal_admin", "brazil_tax", "out_of_scope", "spam", "undeliverable",
];

const KNOWN_LANGUAGES = ["en", "es", "ja", "other"];

const SIGNAL_VAR_OPTIONS = [
  { value: "intent_confidence", label: "Intent confidence",
    hint: "How sure the Stage-1 classifier was about the intent (0–1)." },
  { value: "extraction_completeness", label: "Extraction completeness",
    hint: "Share of required fields successfully extracted (0–1)." },
  { value: "customer_match_score", label: "Customer match score",
    hint: "How confidently the sender mapped to a Salesforce account (0–1)." },
];

function RubricRuleEditor({
  rule,
  onUpdate,
  namespace,
}: {
  rule: Rule;
  onUpdate: (r: Rule) => void;
  namespace: Tab;
}) {
  type Body = Record<string, any>;
  const initial: Body = useMemo(() => rule.body || {}, [rule.body, rule.id, rule.version]);
  const [draft, setDraft] = useState<Body>(initial);
  const [showRaw, setShowRaw] = useState(false);
  const [rawText, setRawText] = useState(JSON.stringify(initial, null, 2));
  const [parseError, setParseError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(initial);
    setRawText(JSON.stringify(initial, null, 2));
    setParseError(null);
  }, [initial, rule.id, rule.version]);

  // Both views share state by serializing draft → rawText whenever the form
  // mutates, and parsing rawText → draft whenever the raw textarea changes.
  const updateDraft = (next: Partial<Body>) => {
    const merged = { ...draft, ...next };
    setDraft(merged);
    setRawText(JSON.stringify(merged, null, 2));
  };

  const onRawChange = (s: string) => {
    setRawText(s);
    try {
      const parsed = JSON.parse(s);
      setDraft(parsed);
      setParseError(null);
    } catch (e: any) {
      setParseError(`Invalid JSON: ${e.message}`);
    }
  };

  const formDirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const resetForm = () => {
    setDraft(initial);
    setRawText(JSON.stringify(initial, null, 2));
    setParseError(null);
  };
  const onSave = async () => {
    setSaving(true);
    try {
      const updated = await saveRule(rule, draft);
      onUpdate(updated);
    } finally {
      setSaving(false);
    }
  };

  const kind: string = (draft.kind || initial.kind || "").toLowerCase();
  const isIntentNamespace = namespace === "intent_confidence_rubric";
  const isLangNamespace = namespace === "language_confidence_rubric";
  const overrideKey = isLangNamespace ? "per_language_overrides" : "per_intent_overrides";
  const overrideOptions = isLangNamespace ? KNOWN_LANGUAGES : KNOWN_INTENTS;

  return (
    <div className="card overflow-hidden">
      <RuleHeader
        rule={rule}
        onSaved={onUpdate}
        onReverted={resetForm}
        saving={saving}
        setSaving={setSaving}
        body={draft}
        resetForm={resetForm}
        formDirty={formDirty}
        onSave={onSave}
      />
      <NamespaceExplainer namespace={namespace} />

      <div className="px-4 py-2.5 border-b border-zbrain-divider bg-emerald-50/40 flex items-center gap-3">
        <div className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold">Rule kind</div>
        <span className="pill bg-white border border-emerald-200 text-emerald-800 text-xs font-medium">
          {kindLabel(kind)}
        </span>
        <div className="text-[12px] text-zbrain-ink/70 leading-snug flex-1">{summarizeRubricRule(draft)}</div>
      </div>

      <div className="p-4 space-y-5">
        {!showRaw && (
          <>
            {kind === "base" && (
              <FormField label="Starting prior (the score every case begins from before any rule is applied)">
                <div className="flex items-center gap-3 max-w-md">
                  <input
                    type="number"
                    min={0} max={1} step={0.01}
                    value={Number.isFinite(Number(draft.value)) ? Number(draft.value) : 0}
                    onChange={(e) => updateDraft({ value: Number(e.target.value) })}
                    className="w-32 text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
                  />
                  <div className="text-xs text-zbrain-muted">
                    Acceptable range: 0.00 – 1.00. Today: {String(initial.value ?? "0.00")}.
                  </div>
                </div>
              </FormField>
            )}

            {kind === "weighted_signal" && (
              <>
                <FormField label="Signal to weight (which Stage-1 / Stage-2 number this rule consumes)">
                  <select
                    value={String(draft.signal_var || "")}
                    onChange={(e) => updateDraft({ signal_var: e.target.value })}
                    className="w-full max-w-md text-sm border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
                  >
                    <option value="">(pick a signal)</option>
                    {SIGNAL_VAR_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <div className="text-[11px] text-zbrain-muted mt-1">
                    {SIGNAL_VAR_OPTIONS.find((o) => o.value === draft.signal_var)?.hint || "Select a signal."}
                  </div>
                </FormField>
                <FormField label={`Weight (currently ${Math.round((Number(draft.weight) || 0) * 100)}% of the score)`}>
                  <div className="flex items-center gap-3 max-w-md">
                    <input
                      type="range" min={0} max={1} step={0.01}
                      value={Number.isFinite(Number(draft.weight)) ? Number(draft.weight) : 0}
                      onChange={(e) => updateDraft({ weight: Number(e.target.value) })}
                      className="flex-1"
                    />
                    <input
                      type="number" min={0} max={1} step={0.01}
                      value={Number.isFinite(Number(draft.weight)) ? Number(draft.weight) : 0}
                      onChange={(e) => updateDraft({ weight: Number(e.target.value) })}
                      className="w-20 text-sm border border-zbrain-divider rounded-md px-2 py-1.5 text-right"
                    />
                  </div>
                  <div className="text-[11px] text-zbrain-muted mt-1">
                    The three default signals (intent + extraction + customer) should sum to ~1.0. Higher values give this signal more pull.
                  </div>
                </FormField>
              </>
            )}

            {kind === "floor_cap" && (
              <>
                <FormField label="Confidence ceiling (the cap this rule enforces when its predicate is true)">
                  <div className="flex items-center gap-3 max-w-md">
                    <input
                      type="number" min={0} max={1} step={0.01}
                      value={Number.isFinite(Number(draft.cap)) ? Number(draft.cap) : 0}
                      onChange={(e) => updateDraft({ cap: Number(e.target.value) })}
                      className="w-28 text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
                    />
                    <div className="text-[11px] text-zbrain-muted">
                      0.95+ keeps L4 auto. 0.80–0.94 forces L3 one-click. Below 0.80 forces L2 human review.
                    </div>
                  </div>
                </FormField>
                <FormField label="Trigger (boolean expression; when true the ceiling applies)">
                  <textarea
                    rows={3}
                    value={String(draft.predicate || "")}
                    onChange={(e) => updateDraft({ predicate: e.target.value })}
                    spellCheck={false}
                    className="w-full font-mono text-[12px] border border-zbrain-divider rounded-md px-2 py-1.5"
                    placeholder="e.g. customer_match_score < 0.95"
                  />
                  <div className="text-[11px] text-zbrain-muted mt-1">
                    Variables you can reference: <code>intent</code>, <code>intent_confidence</code>, <code>extraction_completeness</code>, <code>customer_match_score</code>, <code>po_number</code>, <code>line_count</code>, <code>reconcile_blocking_count</code>, <code>reconcile_soft_count</code>. Operators: <code>{`< > <= >= == != and or in`}</code>.
                  </div>
                </FormField>
                <FormField label="Limit to specific intents (leave empty to apply to all)">
                  <ChipMultiSelect
                    value={Array.isArray(draft.applies_to_intents) ? draft.applies_to_intents : []}
                    onChange={(v) => updateDraft({ applies_to_intents: v })}
                    options={KNOWN_INTENTS}
                    placeholder="Add an intent…"
                  />
                </FormField>
              </>
            )}

            {(kind === "trigger" || kind === "clearance" || kind === "penalty") && (
              <>
                <FormField label={
                  kind === "penalty"
                    ? "Default delta (negative): how much to subtract from the score when this rule matches"
                    : "Default delta (positive): how much to add to the score when this rule matches"
                }>
                  <div className="flex items-center gap-3 max-w-md">
                    <input
                      type="number" step={0.01}
                      value={Number.isFinite(Number(draft.default_delta)) ? Number(draft.default_delta) : 0}
                      onChange={(e) => updateDraft({ default_delta: Number(e.target.value) })}
                      className="w-28 text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
                    />
                    <div className="text-[11px] text-zbrain-muted">
                      Typical positive deltas: +0.10 to +0.35. Typical penalties: -0.10 to -0.30.
                    </div>
                  </div>
                </FormField>

                <FormField label={`Per-${isLangNamespace ? "language" : "intent"} overrides (leave a row empty to use the default delta)`}>
                  <OverrideMapEditor
                    value={(draft as any)[overrideKey] || {}}
                    onChange={(next) => updateDraft({ [overrideKey]: next })}
                    keyOptions={overrideOptions}
                  />
                </FormField>

                {kind === "trigger" && (
                  <FormField label="Example phrases the LLM should recognise (group by intent or language)">
                    <ExamplesMapEditor
                      value={(draft as any).examples || {}}
                      onChange={(next) => updateDraft({ examples: next })}
                      keyOptions={isLangNamespace ? KNOWN_LANGUAGES : KNOWN_INTENTS}
                    />
                  </FormField>
                )}
              </>
            )}

            {!["base","weighted_signal","floor_cap","trigger","clearance","penalty"].includes(kind) && (
              <div className="p-3 rounded-md border border-amber-200 bg-amber-50 text-[12px] text-amber-900">
                Unknown rule kind <code className="font-mono">{kind || "(blank)"}</code>. Open "Show raw JSON" below to edit by hand.
              </div>
            )}

            <FormField label="Description shown in the rule list">
              <input
                type="text"
                value={String(draft.label || "")}
                onChange={(e) => updateDraft({ label: e.target.value })}
                className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
                placeholder="Short label, shown in the left pane."
              />
            </FormField>
            <FormField label="Long-form explanation (shown when a rule is hovered or expanded)">
              <textarea
                rows={4}
                value={String(draft.description || "")}
                onChange={(e) => updateDraft({ description: e.target.value })}
                className="w-full text-[13px] border border-zbrain-divider rounded-md px-2 py-1.5"
                placeholder="Why this rule exists and when to tune it."
              />
            </FormField>

            <FormField label="Active">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={draft.active !== false}
                  onChange={(e) => updateDraft({ active: e.target.checked })}
                />
                <span className="text-sm">{draft.active !== false ? "Active: this rule is firing in production." : "Inactive: preserved in history but no longer firing."}</span>
              </label>
            </FormField>
          </>
        )}

        <div className="flex items-center justify-between pt-2 border-t border-zbrain-divider/60">
          <label className="flex items-center gap-2 text-[11px] text-zbrain-muted cursor-pointer">
            <input
              type="checkbox"
              checked={showRaw}
              onChange={(e) => setShowRaw(e.target.checked)}
            />
            Show raw JSON (developer view)
          </label>
          {parseError && showRaw && (
            <div className="text-[11px] text-rose-600">{parseError}</div>
          )}
        </div>
        {showRaw && (
          <textarea
            value={rawText}
            onChange={(e) => onRawChange(e.target.value)}
            spellCheck={false}
            className="w-full text-[11px] font-mono p-3 min-h-[240px] border border-zbrain-divider rounded-md focus:border-zbrain focus:outline-none"
          />
        )}
      </div>
    </div>
  );
}

function kindLabel(kind: string): string {
  return ({
    base: "Starting prior",
    weighted_signal: "Signal weight",
    floor_cap: "Floor cap",
    trigger: "Trigger (boost)",
    clearance: "Clean-signal bonus",
    penalty: "Penalty",
  } as Record<string, string>)[kind] || kind || "(unknown)";
}

function ChipMultiSelect({
  value, onChange, options, placeholder,
}: {
  value: string[]; onChange: (v: string[]) => void; options: string[]; placeholder?: string;
}) {
  const [text, setText] = useState("");
  const filtered = options.filter((o) => !value.includes(o) && (text === "" || o.toLowerCase().includes(text.toLowerCase())));
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 items-center mb-1.5">
        {value.length === 0 && (
          <span className="text-[11px] text-zbrain-muted italic">No selection (applies to all).</span>
        )}
        {value.map((v) => (
          <span key={v} className="pill bg-zbrain-50 text-zbrain-ink text-[11px] inline-flex items-center gap-1">
            {v}
            <button
              onClick={() => onChange(value.filter((x) => x !== v))}
              className="text-zbrain-muted hover:text-rose-700"
              aria-label={`remove ${v}`}
            >×</button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          list="rubric-chip-options"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && text.trim()) {
              e.preventDefault();
              if (!value.includes(text.trim())) onChange([...value, text.trim()]);
              setText("");
            }
          }}
          placeholder={placeholder}
          className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 flex-1 max-w-sm"
        />
        <datalist id="rubric-chip-options">
          {filtered.map((o) => <option key={o} value={o} />)}
        </datalist>
        <button
          type="button"
          onClick={() => {
            if (text.trim() && !value.includes(text.trim())) {
              onChange([...value, text.trim()]);
              setText("");
            }
          }}
          className="text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50"
        >Add</button>
      </div>
    </div>
  );
}

function OverrideMapEditor({
  value, onChange, keyOptions,
}: {
  value: Record<string, number>;
  onChange: (v: Record<string, number>) => void;
  keyOptions: string[];
}) {
  const entries = Object.entries(value);
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState<string>("");
  return (
    <div>
      {entries.length === 0 && (
        <div className="text-[11px] text-zbrain-muted italic mb-1">No overrides; the default delta applies to every {keyOptions.length === KNOWN_LANGUAGES.length ? "language" : "intent"}.</div>
      )}
      <div className="space-y-1">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-center gap-2">
            <span className="pill bg-zbrain-50 text-zbrain-ink text-[11px] w-44">{k}</span>
            <input
              type="number" step={0.01}
              value={v}
              onChange={(e) => onChange({ ...value, [k]: Number(e.target.value) })}
              className="w-28 text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
            />
            <button
              onClick={() => {
                const next = { ...value }; delete next[k]; onChange(next);
              }}
              className="text-[11px] text-zbrain-muted hover:text-rose-700"
            >Remove</button>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 mt-2 pt-2 border-t border-zbrain-divider/60">
        <select
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 w-44 bg-white"
        >
          <option value="">(add override…)</option>
          {keyOptions.filter((o) => !(o in value)).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <input
          type="number" step={0.01}
          value={newVal}
          onChange={(e) => setNewVal(e.target.value)}
          placeholder="delta"
          className="w-28 text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
        />
        <button
          type="button"
          onClick={() => {
            if (newKey && newVal !== "") {
              onChange({ ...value, [newKey]: Number(newVal) });
              setNewKey(""); setNewVal("");
            }
          }}
          className="text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50"
        >Add</button>
      </div>
    </div>
  );
}

function ExamplesMapEditor({
  value, onChange, keyOptions,
}: {
  value: Record<string, string[]>;
  onChange: (v: Record<string, string[]>) => void;
  keyOptions: string[];
}) {
  const entries = Object.entries(value);
  const [newKey, setNewKey] = useState("");
  return (
    <div className="space-y-2">
      {entries.length === 0 && (
        <div className="text-[11px] text-zbrain-muted italic">No examples yet.</div>
      )}
      {entries.map(([k, list]) => (
        <div key={k} className="border border-zbrain-divider rounded-md p-2">
          <div className="flex items-center justify-between mb-1.5">
            <span className="pill bg-zbrain-50 text-zbrain-ink text-[11px]">{k}</span>
            <button
              onClick={() => {
                const next = { ...value }; delete next[k]; onChange(next);
              }}
              className="text-[11px] text-zbrain-muted hover:text-rose-700"
            >Remove group</button>
          </div>
          <ChipMultiSelect
            value={list}
            onChange={(v) => onChange({ ...value, [k]: v })}
            options={[]}
            placeholder='Add an example phrase, then press Enter…'
          />
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1">
        <select
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 bg-white"
        >
          <option value="">(add group…)</option>
          {keyOptions.filter((o) => !(o in value)).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        <button
          type="button"
          onClick={() => {
            if (newKey && !(newKey in value)) {
              onChange({ ...value, [newKey]: [] });
              setNewKey("");
            }
          }}
          className="text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50"
        >Add group</button>
      </div>
    </div>
  );
}

// ============================================================================
// SmartBodyEditor — generic, introspecting form for any KB rule body the
// platform doesn't have a bespoke editor for. Walks the JSON tree and
// renders sensible form controls per field: strings → text input (long
// strings → textarea), numbers → number input (or 0–1 slider when the field
// name suggests a probability/weight), booleans → checkbox, list[string] →
// chip-list, list[number] → list-of-numbers, list[dict] → table, nested
// dict → recursive section. Field names get a friendly plain-English label
// from the FIELD_GLOSSARY below, with a tooltip explaining what each
// internal field means.
// ============================================================================

const FIELD_GLOSSARY: Record<string, { label: string; hint?: string }> = {
  label:        { label: "Display label", hint: "Short name shown in the rule list." },
  description:  { label: "Description",   hint: "Full explanation of what this rule does and when to tune it." },
  active:       { label: "Active",        hint: "Off-switch. Inactive rules are preserved but do not fire." },
  enabled:      { label: "Enabled",       hint: "Off-switch. Disabled rules are preserved but do not evaluate." },
  severity:     { label: "Severity",      hint: "How serious this rule's outcome is when triggered." },
  predicate:    { label: "Predicate",     hint: "Boolean expression evaluated against the case. When true, the rule fires." },
  invariant:    { label: "Invariant",     hint: "Boolean expression that must remain TRUE. If it goes false at the evaluate-at step, the rule fires." },
  applies_when: { label: "Applies when",  hint: "Boolean expression scoping which cases this rule applies to. Empty = always." },
  fires_when:   { label: "Fires when",    hint: "Whether the rule fires when the predicate is true, false, or always." },
  evaluate_at:  { label: "Evaluate at",   hint: "Pipeline stage where the verifier checks the invariant." },
  mode:         { label: "Mode",          hint: "active = enforced. shadow = scored but no action taken." },
  scope:        { label: "Scope",         hint: "per_line = evaluated per PO line. per_total = evaluated once against the whole case." },
  applies_to_intents: { label: "Limits to intents", hint: "Empty list = applies to every intent." },
  applies_to:   { label: "Applies to",    hint: "Where this rule applies (inbound, outbound, both)." },
  region:       { label: "Limits to regions", hint: "Empty list = applies to every region." },
  priority:     { label: "Priority",      hint: "Lower numbers fire first when multiple rules match." },
  score_weight: { label: "Score weight",  hint: "How much this rule contributes when matched." },
  weight:       { label: "Weight",        hint: "Numeric coefficient applied when matched." },
  threshold:    { label: "Threshold",     hint: "Cutoff value for this rule." },
  regex:        { label: "Regex pattern", hint: "Regular expression matched against the field below." },
  pattern:      { label: "Regex pattern", hint: "Regular expression matched against the field below." },
  field:        { label: "Field matched", hint: "Which part of the email/case the regex runs against (subject / body / from)." },
  flags:        { label: "Regex flags",   hint: "Regex flags. Empty = case-sensitive, multi-line off." },
  category:     { label: "Category",      hint: "Internal grouping label for this rule." },
  source:       { label: "Source",        hint: "Where this rule originated (custom / seed / imported)." },
  english:      { label: "English term",  hint: "Canonical English wording." },
  translations: { label: "Translations",  hint: "Per-language translations of the English term. Keys: language code." },
  preserve_acronym: { label: "Preserve as-is", hint: "If true, the acronym is never translated." },
  domain:       { label: "Domain",        hint: "Business domain this glossary entry applies to." },
  rationale:    { label: "Rationale",     hint: "Why this rule exists. Helps an operator decide if it still applies." },
  patterns:     { label: "Regex patterns", hint: "Patterns the translator preserves verbatim." },
  terms:        { label: "Verbatim terms", hint: "Terms that are never translated." },
  examples_positive: { label: "Positive examples", hint: "Phrases that mean this intent applies." },
  examples_negative: { label: "Negative examples", hint: "Phrases that look related but should NOT be this intent." },
  keywords:     { label: "Keywords",      hint: "Trigger phrases for this rule." },
  message:      { label: "Message",       hint: "Text shown to the CSR when this rule fires." },
  issue_kind:   { label: "Issue kind",    hint: "Machine-readable category written to the trace event." },
  default_tracks: { label: "Default tracks", hint: "Pipeline tracks this owner handles." },
  ai_handled:   { label: "AI handled",    hint: "If true, this queue is processed by an AI service rather than a human." },
  salesforce:   { label: "Salesforce mapping", hint: "Which Salesforce queue this owner maps to." },
  corrective_action: { label: "Corrective action", hint: "What the verifier does when the invariant fails." },
  block:        { label: "Unicode block", hint: "Range of code points this rule covers." },
  per_intent_overrides: { label: "Per-intent overrides", hint: "Override the default delta for specific intents." },
  per_language_overrides: { label: "Per-language overrides", hint: "Override the default delta for specific languages." },
  kind:         { label: "Kind",          hint: "Rule kind (structural; controls which fields apply)." },
  cap:          { label: "Cap",           hint: "Confidence ceiling enforced by this rule." },
  value:        { label: "Value",         hint: "Numeric value carried by this rule." },
  default_delta: { label: "Default delta", hint: "How much this rule moves the score when it matches." },
  signal_var:   { label: "Signal variable", hint: "Which upstream signal this rule consumes." },
};

const SLIDER_FIELDS = new Set(["weight", "score_weight", "cap", "threshold", "default_delta", "value"]);
const DROPDOWN_FIELDS: Record<string, string[]> = {
  severity:     ["hard", "soft", "warn", "block", "review_recommended", "block_until_enriched", "low", "medium", "high", "info", "definitive"],
  scope:        ["per_line", "per_total"],
  mode:         ["active", "shadow"],
  fires_when:   ["predicate_true", "predicate_false"],
  field:        ["subject", "body", "from", "from_address", "to", "headers"],
  evaluate_at:  ["intake", "extract", "decide", "execute", "communicate", "final"],
  kind:         ["base", "weighted_signal", "floor_cap", "trigger", "clearance", "penalty", "rule", "preserve_verbatim", "tone_guidance", "format_guidance", "unicode_block"],
};

function prettifyLabel(name: string): string {
  if (FIELD_GLOSSARY[name]) return FIELD_GLOSSARY[name].label;
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function SmartBodyEditor({ body, onChange }: { body: any; onChange: (next: any) => void }) {
  if (body == null || typeof body !== "object") {
    return <div className="text-[12px] text-zbrain-muted italic">Body is not a JSON object. Use Show raw JSON below.</div>;
  }
  const entries = Object.entries(body);
  if (entries.length === 0) {
    return <div className="text-[12px] text-zbrain-muted italic">(empty body; toggle Show raw JSON to start it.)</div>;
  }
  // Sort: structural fields first (kind, label, severity), then everything
  // except description and active, then description, then active at the
  // bottom. This puts the "what is this rule" header at the top.
  const sortKey = (k: string) => {
    if (k === "kind") return 0;
    if (k === "label") return 1;
    if (k === "severity") return 2;
    if (k === "description") return 100;
    if (k === "active" || k === "enabled") return 110;
    return 50;
  };
  entries.sort((a, b) => sortKey(a[0]) - sortKey(b[0]));

  const update = (k: string, v: any) => onChange({ ...body, [k]: v });
  return (
    <div className="space-y-3">
      {entries.map(([k, v]) => (
        <SmartField key={k} name={k} value={v} onChange={(nv) => update(k, nv)} />
      ))}
    </div>
  );
}

function SmartField({ name, value, onChange }: { name: string; value: any; onChange: (v: any) => void }) {
  const gloss = FIELD_GLOSSARY[name];
  const label = prettifyLabel(name);
  const hint = gloss?.hint;
  const isLongString = typeof value === "string" && value.length > 80;

  // Boolean → checkbox
  if (typeof value === "boolean") {
    return (
      <FieldShell name={name} label={label} hint={hint}>
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} />
          <span className="text-sm">{value ? "Yes" : "No"}</span>
        </label>
      </FieldShell>
    );
  }
  // Number → number input (or 0-1 slider for known probability fields)
  if (typeof value === "number") {
    if (SLIDER_FIELDS.has(name) && value >= 0 && value <= 1) {
      return (
        <FieldShell name={name} label={label} hint={hint}>
          <div className="flex items-center gap-3 max-w-md">
            <input type="range" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(Number(e.target.value))} className="flex-1" />
            <input type="number" min={0} max={1} step={0.01} value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-20 text-sm border border-zbrain-divider rounded-md px-2 py-1.5 text-right" />
          </div>
        </FieldShell>
      );
    }
    return (
      <FieldShell name={name} label={label} hint={hint}>
        <input type="number" step="any" value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-32 text-sm border border-zbrain-divider rounded-md px-2 py-1.5" />
      </FieldShell>
    );
  }
  // String → dropdown (if known enum), textarea (if long), text input (otherwise)
  if (typeof value === "string") {
    if (DROPDOWN_FIELDS[name]) {
      const opts = DROPDOWN_FIELDS[name]!;
      const allOpts = opts.includes(value) ? opts : [...opts, value];
      return (
        <FieldShell name={name} label={label} hint={hint}>
          <select value={value} onChange={(e) => onChange(e.target.value)} className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 bg-white">
            {allOpts.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </FieldShell>
      );
    }
    if (isLongString || /\n/.test(value) || name === "description" || name === "rationale" || name === "predicate" || name === "invariant" || name === "applies_when") {
      const mono = /predicate|invariant|applies_when|regex|pattern/.test(name);
      return (
        <FieldShell name={name} label={label} hint={hint}>
          <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={4} spellCheck={!mono} className={`w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5 ${mono ? "font-mono text-[12px]" : ""}`} />
        </FieldShell>
      );
    }
    return (
      <FieldShell name={name} label={label} hint={hint}>
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} className="w-full max-w-xl text-sm border border-zbrain-divider rounded-md px-2 py-1.5" />
      </FieldShell>
    );
  }
  // Array
  if (Array.isArray(value)) {
    const allStrings = value.every((x) => typeof x === "string");
    const allNumbers = value.every((x) => typeof x === "number");
    if (allStrings) {
      return (
        <FieldShell name={name} label={label} hint={hint}>
          <SmartChipList value={value} onChange={onChange} />
        </FieldShell>
      );
    }
    if (allNumbers) {
      return (
        <FieldShell name={name} label={label} hint={hint}>
          <input type="text" value={value.join(", ")} onChange={(e) => onChange(e.target.value.split(",").map((s) => Number(s.trim())).filter((n) => !isNaN(n)))} className="w-full max-w-xl text-sm border border-zbrain-divider rounded-md px-2 py-1.5" />
          <div className="text-[11px] text-zbrain-muted mt-1">Comma-separated numbers.</div>
        </FieldShell>
      );
    }
    // List of dicts → render as cards
    return (
      <FieldShell name={name} label={label} hint={hint}>
        <div className="space-y-2">
          {value.length === 0 && <div className="text-[11px] text-zbrain-muted italic">No entries.</div>}
          {value.map((item, i) => (
            <div key={i} className="border border-zbrain-divider rounded-md p-2 bg-white">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] uppercase tracking-wider text-zbrain-muted font-semibold">Entry {i + 1}</span>
                <button onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-[11px] text-zbrain-muted hover:text-rose-700">Remove</button>
              </div>
              {typeof item === "object" && item != null ? (
                <SmartBodyEditor body={item} onChange={(nv) => onChange(value.map((x, j) => j === i ? nv : x))} />
              ) : (
                <input type="text" value={String(item ?? "")} onChange={(e) => onChange(value.map((x, j) => j === i ? e.target.value : x))} className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5" />
              )}
            </div>
          ))}
          <button onClick={() => onChange([...value, value.length > 0 && typeof value[0] === "object" ? {} : ""])} className="text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50">Add entry</button>
        </div>
      </FieldShell>
    );
  }
  // Nested dict
  if (typeof value === "object" && value !== null) {
    return (
      <FieldShell name={name} label={label} hint={hint}>
        <div className="pl-3 border-l-2 border-zbrain-divider/70">
          <SmartBodyEditor body={value} onChange={onChange} />
        </div>
      </FieldShell>
    );
  }
  // Null / undefined
  return (
    <FieldShell name={name} label={label} hint={hint}>
      <input type="text" value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value || null)} className="w-full max-w-xl text-sm border border-zbrain-divider rounded-md px-2 py-1.5" placeholder="(unset)" />
    </FieldShell>
  );
}

function FieldShell({ name, label, hint, children }: { name: string; label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-1">
        <label htmlFor={name} className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold">{label}</label>
        <span className="text-[10px] text-zbrain-muted/70 font-mono">({name})</span>
      </div>
      {children}
      {hint && <div className="text-[11px] text-zbrain-muted mt-1 leading-snug">{hint}</div>}
    </div>
  );
}

function SmartChipList({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState("");
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 items-center mb-1.5">
        {value.length === 0 && <span className="text-[11px] text-zbrain-muted italic">(empty)</span>}
        {value.map((v, i) => (
          <span key={i} className="pill bg-zbrain-50 text-zbrain-ink text-[11px] inline-flex items-center gap-1">
            {v}
            <button onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-zbrain-muted hover:text-rose-700" aria-label="remove">×</button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { e.preventDefault(); onChange([...value, text.trim()]); setText(""); } }} placeholder="Type a value and press Enter" className="text-sm border border-zbrain-divider rounded-md px-2 py-1.5 flex-1 max-w-sm" />
        <button type="button" onClick={() => { if (text.trim()) { onChange([...value, text.trim()]); setText(""); } }} className="text-xs px-2 py-1 rounded-md border border-zbrain-divider hover:bg-zinc-50">Add</button>
      </div>
    </div>
  );
}

function GenericRuleEditor({
  rule,
  onUpdate,
  namespace,
}: {
  rule: Rule;
  onUpdate: (r: Rule) => void;
  namespace: Tab;
}) {
  const initial = useMemo(() => rule.body || {}, [rule.body, rule.id, rule.version]);
  const [draftBody, setDraftBody] = useState<any>(initial);
  const [rawText, setRawText] = useState<string>(JSON.stringify(initial, null, 2));
  const [showRaw, setShowRaw] = useState(false);
  const [saving, setSaving] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    setDraftBody(initial);
    setRawText(JSON.stringify(initial, null, 2));
    setParseError(null);
  }, [initial, rule.id, rule.version]);

  const formDirty = JSON.stringify(draftBody) !== JSON.stringify(initial);

  const onSave = async () => {
    setSaving(true);
    try {
      const updated = await saveRule(rule, draftBody);
      onUpdate(updated);
    } finally {
      setSaving(false);
    }
  };

  const resetForm = () => {
    setDraftBody(initial);
    setRawText(JSON.stringify(initial, null, 2));
    setParseError(null);
  };

  const namespaceCopy: Record<string, string> = {
    translation: "Glossary + tone rule consumed by the translation tool. The 'body' contains the instruction text injected into the LLM translator's system prompt.",
    spam_heuristic: "Single regex rule evaluated at sub-step 1.2. If 'matched', its score_weight contributes to the spam total; rules above the threshold (3.0) flag the email.",
    language_heuristic: "Single rule in the layered language detector. Tier 1=script (definitive), 2=diacritic, 3=keyword-density, 4=greeting. First definitive match wins; otherwise highest severity wins.",
    intent_confidence_rubric: (
      "Confidence rubric the intake classifier (sub-step 1.7) applies to score the chosen intent. " +
      "Math: final_confidence = base + sum(matched deltas), clamped to [0, 1]. " +
      "The LLM is forced (via strict JSON Schema) to evaluate every rule below and return matched/delta/evidence; the server recomputes the final number from the breakdown, applying per-intent overrides if present. " +
      "How to optimize: raise default_delta on a rule if real-world results show that signal is under-credited; add a per_intent_overrides entry when one specific intent needs a different weight (e.g. service_order weighing 'subject_explicit_signal' more heavily because the verb is unambiguous); deactivate a rule (active=false) to disable without deleting; edit _base to recalibrate the system's overall confidence floor."
    ),
    language_confidence_rubric: (
      "Confidence rubric the language detector (sub-step 1.4) applies to score the chosen language (en | es | ja | other). " +
      "Math: final_confidence = base + sum(matched deltas), clamped to [0, 1]. " +
      "The LLM evaluates each rule below and returns matched/delta/evidence; the server recomputes the final number, applying per_language_overrides if present. " +
      "How to optimize: raise script_definitive_match's per-language override for ja/es/other if the system is consistently under-confident on those languages despite obvious script cues; lower mixed_language_penalty if too many code-switching emails are getting routed to HITL; tune _base if real-world calibration data shows over- or under-confidence on the median email."
    ),
    translation_glossary: (
      "Per-language Keysight glossary. Each row is ONE Keysight concept (e.g. 'calibration certificate', " +
      "'work order', 'ECCN') with its canonical translation in every supported customer language. " +
      "Stage 1.5 (inbound: customer language → English) reads the customer-language column to map " +
      "native terms to canonical English. Stage 5.1 (reply drafting in customer language) reads the " +
      "English column → customer-language column to write replies with the right Keysight phrasing. " +
      "Acronyms flagged with `preserve_acronym` (PO, SOA, BOM, OOT, ECCN, ITAR, EAR, SLA, SKU, NPI, EOL) " +
      "stay verbatim in every language. " +
      "How to optimize: when adding a new customer language, add the language code to every row's " +
      "`translations` dict: one rule, all concepts. To add a new term, add a new row with a unique " +
      "`id` and translations for the languages you support today. To deprecate a term, set active=false; " +
      "do not delete (preserves audit history)."
    ),
    reconcile_checks: (
      "Stage 2.5 cross-system validations. Each row is one predicate-driven check that runs " +
      "after extraction completes. Two scopes: per_line (evaluated once per PO line item against " +
      "the matched quote line) and per_total (evaluated once against extracted PO totals + the " +
      "matched account / recent orders). Severity controls how the result feeds into the Stage 3 " +
      "confidence formula: 'hard' issues cap confidence at 0.70, 'soft' at 0.88, 'warn' shows in " +
      "trace only. The 12 defaults cover the RFP §37 'pricing, quantities, terms' requirement and " +
      "extend it with totals, currency, billing-address, incoterms, payment-terms, and duplicate-PO " +
      "detection. " +
      "How to optimize: tighten a tolerance (e.g., line_unit_price_matches_quote default of $0.01) " +
      "if your contracts allow stricter price matching; loosen by raising the predicate threshold " +
      "if your suppliers' POs naturally drift; deactivate (active=false) checks that don't apply " +
      "to your deployment without deleting them; raise a check's severity from 'warn' → 'soft' → " +
      "'hard' to escalate L4 prevention. New checks can be added; predicate vocabulary mirrors " +
      "business_rules: po_line, quote_line, quote_skus, extracted_total, quote_total, " +
      "quote_currency, account, recent_orders, fuzzy_match_score. Each check compiles to a Python " +
      "AST safely-evaluated against the eval context; no arbitrary code execution risk."
    ),
    decision_confidence_rubric: (
      "Stage 3.1 confidence formula, auditable and tunable. Two rule kinds drive the math: " +
      "weighted_signal contributes 'weight × signal_var' (the 3 default signals: intent_confidence × 0.45, extraction_completeness × 0.35, customer_match_score × 0.20, summing to 1.0). " +
      "floor_cap rules force confidence down to a fixed value when their predicate evaluates true (e.g., customer_match < 0.95 → cap at 0.85, which keeps fuzzy-name-matched customers out of L4 auto). " +
      "Final confidence = clamp(base + Σ weighted_signals, 0, 1), then stepped through every cap in priority order. The Stage 3.1 trace UI shows exactly which rules contributed and which caps fired. " +
      "How to optimize: rebalance the three weights to favor a different signal (e.g., raise customer_match weight in regulated industries); tighten the customer-match caps for stricter L4 gating; add a new floor_cap rule for any business policy ('total > $X always L2', 'EOL SKU never L4', etc.); deactivate (active=false) a cap that isn't relevant to your deployment without deleting it. Predicate vocabulary mirrors the business_rules sandbox: intent, intent_confidence, extraction_completeness, customer_match_score, po_number, line_count, reconcile_blocking_count, reconcile_soft_count."
    ),
  };

  return (
    <div className="card overflow-hidden">
      <RuleHeader
        rule={rule}
        onSaved={onUpdate}
        onReverted={resetForm}
        saving={saving}
        setSaving={setSaving}
        body={initial}
        resetForm={resetForm}
        formDirty={formDirty}
        onSave={onSave}
      />
      {KB_EXPLAINERS[namespace] ? (
        <NamespaceExplainer namespace={namespace} />
      ) : namespaceCopy[namespace] ? (
        <div className="px-4 py-2 border-b border-zbrain-divider text-xs text-zbrain-muted">
          {namespaceCopy[namespace]}
        </div>
      ) : null}
      {(() => {
        const summary = summarizeRubricRule(initial);
        if (!summary) return null;
        return (
          <div className="px-4 py-2.5 border-b border-zbrain-divider bg-emerald-50/40 text-[13px] text-zbrain-ink">
            <span className="text-[10px] uppercase tracking-wider text-emerald-700 font-semibold mr-2">What this rule does</span>
            {summary}
          </div>
        );
      })()}
      <div className="p-4 space-y-4">
        {!showRaw && (
          <SmartBodyEditor
            body={draftBody}
            onChange={(next) => {
              setDraftBody(next);
              setRawText(JSON.stringify(next, null, 2));
            }}
          />
        )}

        <div className="flex items-center justify-between pt-2 border-t border-zbrain-divider/60">
          <label className="flex items-center gap-2 text-[11px] text-zbrain-muted cursor-pointer">
            <input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} />
            Show raw JSON (developer view)
          </label>
          {parseError && showRaw && (
            <div className="text-[11px] text-rose-600">{parseError}</div>
          )}
        </div>
        {showRaw && (
          <textarea
            value={rawText}
            onChange={(e) => {
              setRawText(e.target.value);
              try {
                setDraftBody(JSON.parse(e.target.value));
                setParseError(null);
              } catch (err: any) {
                setParseError(`Invalid JSON: ${err.message}`);
              }
            }}
            spellCheck={false}
            className="w-full text-[11px] font-mono p-3 min-h-[260px] border border-zbrain-divider rounded-md focus:border-zbrain focus:outline-none"
          />
        )}

        {namespace === "pipeline_verification_rules" && (
          <RuleBackTestPanel rawText={rawText} />
        )}
      </div>
    </div>
  );
}

/** Back-test a verification rule against the most recent pipelines so the
 * operator can see how the rule behaves on real historical cases before
 * promoting it from shadow to active. */
function RuleBackTestPanel({ rawText }: { rawText: string }) {
  const [limit, setLimit] = useState<number>(200);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const onRun = async () => {
    setErr(null);
    setResult(null);
    let body: any;
    try {
      body = JSON.parse(rawText);
    } catch (e: any) {
      setErr(`Invalid JSON: ${e.message}`);
      return;
    }
    setBusy(true);
    try {
      const r = await api.system.simulateVerificationRule(body, limit);
      setResult(r);
    } catch (e: any) {
      setErr(e?.message || "Simulation failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-md border border-zbrain-divider bg-zbrain-surface/30 p-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="text-[10px] uppercase tracking-[0.14em] font-semibold text-zbrain-muted">
          Back-test against historical pipelines
        </div>
        <span className="text-[11px] text-zbrain-muted">
          Evaluate the rule body above against the most recent N pipelines without saving. Safe to use in shadow mode before promoting to active.
        </span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <label className="text-[11.5px] text-zbrain-ink">
          N pipelines:
          <input
            type="number"
            min={10}
            max={1000}
            value={limit}
            onChange={(e) => setLimit(Math.max(10, Math.min(1000, Number(e.target.value) || 200)))}
            className="ml-2 w-24 border border-zbrain-divider rounded px-2 py-1 text-[12px]"
          />
        </label>
        <button onClick={onRun} disabled={busy} className="btn-primary text-xs">
          {busy ? "Running…" : "Run back-test"}
        </button>
        {err && <span className="text-[11px] text-rose-700">{err}</span>}
      </div>
      {result && (
        <div className="mt-3 space-y-2">
          <div className="grid grid-cols-5 gap-2 text-center">
            <div className="rounded border border-zbrain-divider bg-white px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">Checked</div>
              <div className="text-sm font-semibold tabular-nums">{result.checked_pipelines}</div>
            </div>
            <div className="rounded border border-zbrain-divider bg-white px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">Applied</div>
              <div className="text-sm font-semibold tabular-nums">{result.rule_applied_count}</div>
            </div>
            <div className="rounded border border-zbrain-divider bg-white px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-emerald-700">Pass</div>
              <div className="text-sm font-semibold tabular-nums text-emerald-700">{result.rule_passed_count}</div>
            </div>
            <div className="rounded border border-zbrain-divider bg-white px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-rose-700">Fail</div>
              <div className="text-sm font-semibold tabular-nums text-rose-700">{result.rule_failed_count}</div>
            </div>
            <div className="rounded border border-zbrain-divider bg-white px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-zbrain-muted">Error</div>
              <div className="text-sm font-semibold tabular-nums">{result.rule_error_count}</div>
            </div>
          </div>
          <div className="text-[11px] text-zbrain-muted">
            Match rate {result.match_rate_pct}% · Fail rate {result.fail_rate_pct}% of cases it applies to
          </div>
          {result.results && result.results.length > 0 && (
            <details className="text-[11.5px]">
              <summary className="cursor-pointer text-zbrain hover:underline font-medium">
                Per-pipeline breakdown ({result.results.length})
              </summary>
              <div className="mt-2 max-h-72 overflow-auto">
                <table className="w-full text-[11px]">
                  <thead className="text-zbrain-muted text-left border-b border-zbrain-divider">
                    <tr>
                      <th className="py-1 pr-2 font-medium">Pipeline</th>
                      <th className="py-1 pr-2 font-medium">Intent</th>
                      <th className="py-1 pr-2 font-medium">Tier</th>
                      <th className="py-1 pr-2 font-medium">Status</th>
                      <th className="py-1 pr-2 font-medium">Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.results.map((r: any) => (
                      <tr key={r.pipeline_id} className="border-b border-zbrain-divider/40">
                        <td className="py-1 pr-2 font-mono">
                          <a href={`/trace/${r.pipeline_id}`} className="text-zbrain hover:underline" target="_blank" rel="noreferrer">
                            #{r.pipeline_id}
                          </a>
                        </td>
                        <td className="py-1 pr-2">{r.intent || "-"}</td>
                        <td className="py-1 pr-2 font-mono">{r.tier || "-"}</td>
                        <td className="py-1 pr-2">{r.status || "-"}</td>
                        <td className={`py-1 pr-2 font-medium ${
                          r.verdict === "pass" ? "text-emerald-700"
                          : r.verdict === "fail" ? "text-rose-700"
                          : r.verdict === "error" ? "text-rose-700"
                          : "text-zbrain-muted"
                        }`}>{r.verdict}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function AddBusinessRuleModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (key: string) => void;
}) {
  const [key, setKey] = useState("");
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const keyValid = /^[a-z][a-z0-9_]*$/.test(key);

  const onSubmit = async () => {
    if (!keyValid || !label.trim()) return;
    setBusy(true);
    try {
      const defaultBody = {
        predicate: "total > 0",
        severity: "warn",
        message: "",
        applies_to_intents: [],
        region: [],
        priority: 50,
        active: true,
      };
      const r = await fetch(`/api/kb/business_rules/${key}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: defaultBody, label, description }),
      });
      if (!r.ok) {
        alert(`Failed to create rule: ${r.status}`);
        return;
      }
      onCreated(key);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={onClose}>
      <div
        className="card w-[480px] max-w-[90vw] p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <h2 className="text-base font-semibold">Add business rule</h2>
          <p className="text-xs text-zbrain-muted mt-0.5">
            Creates a new rule with a placeholder predicate. Edit the predicate, severity, and intents after.
          </p>
        </div>
        <FormField label="Key (snake_case)">
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="e.g. minority_owned_priority"
            className="w-full text-sm font-mono border border-zbrain-divider rounded-md px-2 py-1.5"
          />
          {key && !keyValid && (
            <div className="text-[11px] text-rose-600 mt-1">
              Keys must start with a lowercase letter and contain only lowercase, digits, underscores.
            </div>
          )}
        </FormField>
        <FormField label="Label">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Human-readable rule name"
            className="w-full text-sm border border-zbrain-divider rounded-md px-2 py-1.5"
          />
        </FormField>
        <FormField label="Description">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Why this rule exists"
            className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 min-h-[64px]"
          />
        </FormField>
        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="btn-ghost text-xs">
            Cancel
          </button>
          <button
            onClick={onSubmit}
            disabled={busy || !keyValid || !label.trim()}
            className="btn-primary text-xs"
          >
            {busy ? "Creating…" : "Create rule"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Translation glossary editor and "Add term" modal.
//
// The functional team adds new Keysight terminology often (calibration jargon,
// SKU family names, region-specific acronyms). The generic JSON editor makes
// that too tedious. This editor renders a typed form: English phrase, every
// supported customer language as its own labelled input, a domain dropdown,
// applies-to checkboxes (inbound translator vs outbound reply drafter), and
// an optional "preserve acronym" toggle. No JSON. No structure to guess.
//
// Supported customer languages are derived from the existing rows so adding
// a new language anywhere in the seed automatically lights up a new field.
// "es" and "ja" are always shown as base languages.
// ---------------------------------------------------------------------------

const GLOSSARY_BASE_LANGS: { code: string; label: string }[] = [
  { code: "es", label: "Spanish" },
  { code: "ja", label: "Japanese" },
];

const GLOSSARY_DOMAINS = ["service", "order", "billing", "compliance", "logistics", "general"];

type GlossaryBody = {
  label: string;
  description?: string;
  kind: "glossary_term";
  english: string;
  translations: Record<string, string>;
  applies_to: ("inbound" | "outbound")[];
  domain: string;
  preserve_acronym: string | null;
  active: boolean;
};

function emptyGlossaryBody(): GlossaryBody {
  return {
    label: "",
    description: "",
    kind: "glossary_term",
    english: "",
    translations: { es: "", ja: "" },
    applies_to: ["inbound", "outbound"],
    domain: "general",
    preserve_acronym: null,
    active: true,
  };
}

function normalizeGlossary(b: any): GlossaryBody {
  const base = emptyGlossaryBody();
  return {
    ...base,
    ...(b || {}),
    translations: { ...base.translations, ...((b || {}).translations || {}) },
    applies_to: Array.isArray(b?.applies_to) ? b.applies_to : base.applies_to,
  };
}

function GlossaryEditor({ rule, onUpdate }: { rule: Rule; onUpdate: (r: Rule) => void }) {
  const initial = normalizeGlossary(rule.body);
  const [body, setBody] = useState<GlossaryBody>(initial);
  const [label, setLabel] = useState(rule.label || "");
  const [description, setDescription] = useState(rule.description || "");
  const [saving, setSaving] = useState(false);
  const [reverting, setReverting] = useState(false);

  useEffect(() => {
    const fresh = normalizeGlossary(rule.body);
    setBody(fresh);
    setLabel(rule.label || "");
    setDescription(rule.description || "");
  }, [rule.id, rule.version]);

  const dirty = useMemo(() => {
    return (
      JSON.stringify(body) !== JSON.stringify(normalizeGlossary(rule.body)) ||
      label !== (rule.label || "") ||
      description !== (rule.description || "")
    );
  }, [body, rule, label, description]);

  const onSave = async () => {
    setSaving(true);
    try {
      const next = await saveRule(rule, body, label, description);
      onUpdate(next);
    } finally {
      setSaving(false);
    }
  };

  const onRevert = async () => {
    setReverting(true);
    try {
      const next = await resetRule(rule);
      onUpdate(next);
    } finally {
      setReverting(false);
    }
  };

  // Show every language present in any row so the editor is forward-compatible.
  const langs = GLOSSARY_BASE_LANGS;

  const setTranslation = (code: string, value: string) => {
    setBody((b) => ({ ...b, translations: { ...b.translations, [code]: value } }));
  };

  const toggleAppliesTo = (which: "inbound" | "outbound") => {
    setBody((b) => {
      const has = b.applies_to.includes(which);
      const next = has ? b.applies_to.filter((x) => x !== which) : [...b.applies_to, which];
      // Always keep at least one direction so the term is not orphaned.
      return { ...b, applies_to: next.length === 0 ? b.applies_to : next };
    });
  };

  return (
    <div className="card p-5 space-y-5">
      <RuleHeader
        rule={rule}
        onSaved={(r) => onUpdate(r)}
        onReverted={() => undefined}
        saving={saving || reverting}
        setSaving={(v) => setSaving(v)}
        body={body}
        resetForm={() => {
          const fresh = normalizeGlossary(rule.body);
          setBody(fresh);
          setLabel(rule.label || "");
          setDescription(rule.description || "");
        }}
        formDirty={dirty}
        onSave={onSave}
      />

      <div className="grid grid-cols-2 gap-4">
        <FormField label="English phrase">
          <input
            value={body.english}
            onChange={(e) => {
              setBody((b) => ({ ...b, english: e.target.value, label: label || e.target.value }));
              if (!label.trim()) setLabel(e.target.value);
            }}
            placeholder="e.g. calibration certificate"
            className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
          />
        </FormField>
        <FormField label="Domain">
          <select
            value={body.domain}
            onChange={(e) => setBody((b) => ({ ...b, domain: e.target.value }))}
            className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 bg-white"
          >
            {GLOSSARY_DOMAINS.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </FormField>
      </div>

      <div className="space-y-3">
        <div className="text-[11px] uppercase tracking-wider text-zbrain-muted font-semibold">
          Translations
        </div>
        {langs.map((l) => (
          <FormField key={l.code} label={`${l.label} (${l.code})`}>
            <input
              value={body.translations[l.code] || ""}
              onChange={(e) => setTranslation(l.code, e.target.value)}
              placeholder={`Canonical ${l.label} translation`}
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
            />
          </FormField>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <FormField label="Applies to">
          <div className="flex items-center gap-4 text-sm">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={body.applies_to.includes("inbound")}
                onChange={() => toggleAppliesTo("inbound")}
              />
              Inbound (customer language to English)
            </label>
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={body.applies_to.includes("outbound")}
                onChange={() => toggleAppliesTo("outbound")}
              />
              Outbound (English reply to customer language)
            </label>
          </div>
        </FormField>
        <FormField label="Active">
          <label className="inline-flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="checkbox"
              checked={body.active}
              onChange={(e) => setBody((b) => ({ ...b, active: e.target.checked }))}
            />
            Term is active; the translator agent uses this entry
          </label>
        </FormField>
      </div>

      <FormField label="Preserve acronym (optional)">
        <input
          value={body.preserve_acronym || ""}
          onChange={(e) => setBody((b) => ({ ...b, preserve_acronym: e.target.value || null }))}
          placeholder="e.g. ECCN. The translator will keep this token verbatim in both directions."
          className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
        />
      </FormField>

      <FormField label="Why this term matters (optional)">
        <textarea
          value={body.description || ""}
          onChange={(e) => {
            const v = e.target.value;
            setBody((b) => ({ ...b, description: v }));
            setDescription(v);
          }}
          placeholder="A short explanation operators can read when they review this term in the trace."
          className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 min-h-[64px]"
        />
      </FormField>

      <FormField label="Internal label">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Defaults to the English phrase"
          className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
        />
      </FormField>
    </div>
  );
}

function AddGlossaryModal({
  existingKeys,
  onClose,
  onCreated,
}: {
  existingKeys: Set<string>;
  onClose: () => void;
  onCreated: (key: string) => void;
}) {
  const [english, setEnglish] = useState("");
  const [es, setEs] = useState("");
  const [ja, setJa] = useState("");
  const [domain, setDomain] = useState("general");
  const [appliesIn, setAppliesIn] = useState(true);
  const [appliesOut, setAppliesOut] = useState(true);
  const [preserve, setPreserve] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const derivedKey = useMemo(() => slugifyKey(english), [english]);
  const keyConflict = derivedKey && existingKeys.has(derivedKey);
  const ready = english.trim().length > 0 && !keyConflict && (es.trim() || ja.trim());

  const onSubmit = async () => {
    if (!ready) return;
    setBusy(true);
    setErr(null);
    try {
      const body: GlossaryBody = {
        label: english.trim(),
        description: description.trim(),
        kind: "glossary_term",
        english: english.trim(),
        translations: {
          ...(es.trim() ? { es: es.trim() } : {}),
          ...(ja.trim() ? { ja: ja.trim() } : {}),
        },
        applies_to: [
          ...(appliesIn ? (["inbound"] as const) : []),
          ...(appliesOut ? (["outbound"] as const) : []),
        ],
        domain,
        preserve_acronym: preserve.trim() || null,
        active: true,
      };
      const r = await createRule("translation_glossary", {
        key: derivedKey,
        body,
        label: english.trim(),
        description: description.trim(),
      });
      onCreated(r.key);
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-zbrain-ink/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-auto p-6 space-y-4">
        <div>
          <h3 className="text-base font-semibold">Add glossary term</h3>
          <p className="text-xs text-zbrain-muted mt-1">
            The translator agent uses every active glossary term in both the inbound (customer to English) and outbound (English to customer) directions, so an entry you add here applies to every email in any supported language.
          </p>
        </div>

        <FormField label="English phrase">
          <input
            value={english}
            onChange={(e) => setEnglish(e.target.value)}
            placeholder="e.g. calibration certificate"
            className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
            autoFocus
          />
          {keyConflict && (
            <div className="text-[11px] text-rose-700 mt-1">
              An entry with this key already exists ({derivedKey}). Edit the existing term instead.
            </div>
          )}
          {english && !keyConflict && (
            <div className="text-[11px] text-zbrain-muted mt-1">Saved as key: <span className="font-mono">{derivedKey}</span></div>
          )}
        </FormField>

        <div className="grid grid-cols-2 gap-4">
          <FormField label="Spanish translation">
            <input
              value={es}
              onChange={(e) => setEs(e.target.value)}
              placeholder="Optional"
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
            />
          </FormField>
          <FormField label="Japanese translation">
            <input
              value={ja}
              onChange={(e) => setJa(e.target.value)}
              placeholder="Optional"
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
            />
          </FormField>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <FormField label="Domain">
            <select
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 bg-white"
            >
              {GLOSSARY_DOMAINS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Preserve acronym (optional)">
            <input
              value={preserve}
              onChange={(e) => setPreserve(e.target.value)}
              placeholder="e.g. ECCN"
              className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2"
            />
          </FormField>
        </div>

        <FormField label="Applies to">
          <div className="flex items-center gap-4 text-sm">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={appliesIn} onChange={(e) => setAppliesIn(e.target.checked)} />
              Inbound translator
            </label>
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={appliesOut} onChange={(e) => setAppliesOut(e.target.checked)} />
              Outbound reply drafter
            </label>
          </div>
        </FormField>

        <FormField label="Why this term matters (optional)">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="A short note operators will see when reviewing the trace."
            className="w-full text-sm border border-zbrain-divider rounded-md px-3 py-2 min-h-[64px]"
          />
        </FormField>

        {err && (
          <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded p-2">
            {err}
          </div>
        )}

        <div className="flex items-center justify-end gap-2">
          <button onClick={onClose} className="btn-ghost text-xs">Cancel</button>
          <button onClick={onSubmit} disabled={!ready || busy} className="btn-primary text-xs">
            {busy ? "Adding…" : "Add term"}
          </button>
        </div>
      </div>
    </div>
  );
}
