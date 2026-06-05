import { useEffect, useState } from "react";

/**
 * Notifications settings.
 *
 * Lets the operator pick exactly which events fire a notification (each
 * channel can be toggled independently) and where the outbound channels
 * point. Choices persist in `localStorage` until the backend forwarder is
 * wired; the in-app bell mirrors whatever is selected here.
 */

type TriggerKey =
  | "hitl_new_task"
  | "hitl_status_change"
  | "aioa_fail"
  | "aioa_timeout"
  | "drift_confidence"
  | "drift_segment"
  | "integration_down"
  | "pipeline_error";

type ChannelKey = "in_app" | "slack" | "teams";

const TRIGGERS: { key: TriggerKey; label: string; detail: string }[] = [
  {
    key: "hitl_new_task",
    label: "New HITL task arrives",
    detail: "A pipeline parks at HITL because confidence is below the autonomy threshold or required data is missing.",
  },
  {
    key: "hitl_status_change",
    label: "HITL task assigned or resolved",
    detail: "Operator assignment, approve / edit / reject decisions, and task escalations.",
  },
  {
    key: "aioa_fail",
    label: "AIOA callback returns FAIL",
    detail: "An external validator rejected the pipeline. The CSR clarification draft is attached when present.",
  },
  {
    key: "aioa_timeout",
    label: "AIOA timeout window elapsed",
    detail: "No callback arrived within the configured timeout. Pipeline is rolled to HITL with a clarification draft.",
  },
  {
    key: "drift_confidence",
    label: "Confidence drift detected",
    detail: "Rolling-window classification confidence has dropped below the baseline by more than the configured delta.",
  },
  {
    key: "drift_segment",
    label: "Segment-level accuracy regression",
    detail: "A per-language or per-intent slice degraded enough to trigger the segment drift alarm.",
  },
  {
    key: "integration_down",
    label: "Integration health change",
    detail: "Salesforce, SharePoint, or the mailbox transitions from connected to disconnected (or back).",
  },
  {
    key: "pipeline_error",
    label: "Pipeline error",
    detail: "A pipeline finished in error state. Mirrors the in-app Errors view.",
  },
];

const DEFAULT_MATRIX: Record<TriggerKey, Record<ChannelKey, boolean>> = {
  hitl_new_task:       { in_app: true,  slack: false, teams: false },
  hitl_status_change:  { in_app: true,  slack: false, teams: false },
  aioa_fail:           { in_app: true,  slack: true,  teams: false },
  aioa_timeout:        { in_app: true,  slack: true,  teams: false },
  drift_confidence:    { in_app: true,  slack: true,  teams: false },
  drift_segment:       { in_app: true,  slack: false, teams: false },
  integration_down:    { in_app: true,  slack: true,  teams: true  },
  pipeline_error:      { in_app: true,  slack: false, teams: false },
};

const STORE_KEY = "zbrain-orchestrator:notif-matrix";

function loadMatrix(): Record<TriggerKey, Record<ChannelKey, boolean>> {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return DEFAULT_MATRIX;
    const parsed = JSON.parse(raw);
    // Shallow-merge to preserve newly added triggers when defaults grow.
    const merged: any = { ...DEFAULT_MATRIX };
    for (const k of Object.keys(DEFAULT_MATRIX) as TriggerKey[]) {
      merged[k] = { ...DEFAULT_MATRIX[k], ...(parsed[k] || {}) };
    }
    return merged;
  } catch {
    return DEFAULT_MATRIX;
  }
}

function saveMatrix(m: Record<TriggerKey, Record<ChannelKey, boolean>>) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(m)); } catch { /* noop */ }
}

export function NotificationsSettingsPage() {
  const [matrix, setMatrix] = useState(() => loadMatrix());
  const [slackWebhook, setSlackWebhook] = useState("");
  const [teamsWebhook, setTeamsWebhook] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    try {
      setSlackWebhook(localStorage.getItem("zbrain.notif.slack") || "");
      setTeamsWebhook(localStorage.getItem("zbrain.notif.teams") || "");
    } catch { /* noop */ }
  }, []);

  function toggle(t: TriggerKey, c: ChannelKey) {
    const next = {
      ...matrix,
      [t]: { ...matrix[t], [c]: !matrix[t][c] },
    };
    setMatrix(next);
    saveMatrix(next);
  }

  function setRow(t: TriggerKey, value: boolean) {
    const next = {
      ...matrix,
      [t]: { in_app: value, slack: value, teams: value },
    };
    setMatrix(next);
    saveMatrix(next);
  }

  const saveChannels = () => {
    try {
      localStorage.setItem("zbrain.notif.slack", slackWebhook.trim());
      localStorage.setItem("zbrain.notif.teams", teamsWebhook.trim());
    } catch { /* noop */ }
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="display-md">Notifications</h1>
        <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">
          Pick which platform events fire a notification, and where the outbound channels point.
          The in-app bell mirrors whichever triggers you keep enabled.
        </p>
      </div>

      {/* === Trigger matrix === */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-zbrain-divider flex items-center justify-between gap-4">
          <div>
            <h2 className="text-sm font-semibold">Triggers</h2>
            <p className="text-[11.5px] text-zbrain-muted mt-0.5">
              Per-event, per-channel routing. Disabling every channel for a row mutes that event.
            </p>
          </div>
          <span className="text-[10.5px] uppercase tracking-[0.12em] text-zbrain-muted">
            Persisted to this browser
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="bg-zbrain-surface dark:bg-zbrain-dark-elev2 text-zbrain-muted uppercase tracking-wider text-[10.5px]">
                <th className="px-4 py-2.5 text-left font-semibold w-[44%]">Trigger</th>
                <th className="px-4 py-2.5 text-center font-semibold">In-app bell</th>
                <th className="px-4 py-2.5 text-center font-semibold">Slack</th>
                <th className="px-4 py-2.5 text-center font-semibold">Teams</th>
                <th className="px-4 py-2.5 text-right font-semibold">Bulk</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zbrain-divider dark:divide-zbrain-dark-divider">
              {TRIGGERS.map((t) => (
                <tr key={t.key} className="hover:bg-zbrain-surface/40 dark:hover:bg-zbrain-dark-elev2/50">
                  <td className="px-4 py-3 align-top">
                    <div className="font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">{t.label}</div>
                    <div className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5 leading-relaxed">{t.detail}</div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <Toggle on={matrix[t.key].in_app} onChange={() => toggle(t.key, "in_app")} label={`${t.label} → in-app`} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <Toggle on={matrix[t.key].slack} onChange={() => toggle(t.key, "slack")} label={`${t.label} → Slack`} />
                  </td>
                  <td className="px-4 py-3 text-center">
                    <Toggle on={matrix[t.key].teams} onChange={() => toggle(t.key, "teams")} label={`${t.label} → Teams`} />
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <button type="button" onClick={() => setRow(t.key, true)} className="text-[11px] text-zbrain hover:underline">all</button>
                    <span className="text-zbrain-muted opacity-50 mx-1">|</span>
                    <button type="button" onClick={() => setRow(t.key, false)} className="text-[11px] text-zbrain-muted hover:underline">none</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* === Outbound channels === */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-zbrain-divider">
          <h2 className="text-sm font-semibold">Outbound channels</h2>
          <p className="text-xs text-zbrain-muted mt-0.5">
            Paste incoming-webhook URLs from your Slack workspace or Teams channel. The webhook URL is the
            only credential we need; ZBrain never requests OAuth scopes against your workspace.
          </p>
        </div>
        <div className="px-5 py-4 space-y-4">
          <Webhook
            label="Slack incoming webhook"
            placeholder="https://hooks.slack.com/services/T0.../B0.../..."
            help="Create one at Slack workspace settings · Apps · Incoming Webhooks. Pick the channel ZBrain should post to."
            value={slackWebhook}
            onChange={setSlackWebhook}
          />
          <Webhook
            label="Microsoft Teams incoming webhook"
            placeholder="https://outlook.office.com/webhook/..."
            help="Create one on the target Teams channel · Connectors · Incoming Webhook."
            value={teamsWebhook}
            onChange={setTeamsWebhook}
          />
          <div className="flex items-center gap-3 pt-2 border-t border-zbrain-divider">
            <button onClick={saveChannels} className="btn-primary text-xs">
              Save channels
            </button>
            {saved && <span className="text-xs text-emerald-700">Saved locally. Wire the backend forwarder to activate.</span>}
          </div>
          <p className="text-[11px] text-zbrain-muted">
            Webhook URLs are stored client-side only until the workspace administrator runs the backend forwarder.
            Treat them as secrets even so; do not paste into shared sessions.
          </p>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-zbrain-divider">
          <h2 className="text-sm font-semibold">In-app notifications</h2>
        </div>
        <div className="px-5 py-4 text-sm text-zbrain-muted">
          The notification bell on the SalesOps front-end is always on. It pulls from the same event source
          the outbound channels use, so nothing is lost if Slack or Teams is not configured.
        </div>
      </div>
    </div>
  );
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={onChange}
      className={[
        "relative inline-flex h-5 w-9 items-center rounded-full transition-colors",
        on ? "bg-zbrain dark:bg-zbrain-dark-accent" : "bg-zbrain-divider dark:bg-zbrain-dark-divider",
      ].join(" ")}
    >
      <span
        className={[
          "inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform",
          on ? "translate-x-4" : "translate-x-0.5",
        ].join(" ")}
      />
    </button>
  );
}

function Webhook({
  label,
  placeholder,
  help,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  help: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="text-xs uppercase tracking-wider text-zbrain-muted font-medium">{label}</label>
      <input
        className="w-full h-9 px-3 mt-1 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 font-mono text-sm text-zbrain-ink dark:text-zbrain-dark-ink focus:outline-none focus:ring-2 focus:ring-zbrain/30"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        type="password"
      />
      <p className="text-[11.5px] text-zbrain-muted mt-1">{help}</p>
    </div>
  );
}
