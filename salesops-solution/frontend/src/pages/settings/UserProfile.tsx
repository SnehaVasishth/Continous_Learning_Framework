import { Avatar } from "../../components/OperatorPicker";
import { useOperator } from "../../lib/operator";

/**
 * User profile settings.
 *
 * Read-only view of the currently selected Salesforce operator. Identity
 * (name, email, username, rule-owner flag) is sourced live from Salesforce
 * via /api/sf-users and is not editable here. Operators switch identity
 * through the avatar picker in the top right of the header.
 */
export function UserProfileSection() {
  const { current, loaded, error } = useOperator();

  const openPicker = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    window.dispatchEvent(new CustomEvent("operator-picker:open"));
  };

  if (!loaded) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="display-md">User profile</h1>
          <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">
            Loading operator identity from Salesforce.
          </p>
        </div>
        <div className="card p-6 animate-pulse">
          <div className="h-20 w-20 rounded-full bg-slate-100" />
          <div className="h-4 w-40 bg-slate-100 mt-4 rounded" />
          <div className="h-3 w-56 bg-slate-100 mt-2 rounded" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="display-md">User profile</h1>
        </div>
        <div className="card p-6 border-rose-200 bg-rose-50/60">
          <div className="text-sm font-semibold text-rose-800">Operator directory unavailable</div>
          <div className="text-xs text-rose-700 mt-1">{error}</div>
          <div className="text-xs text-rose-700 mt-2">
            Identity is read live from Salesforce. Restore the Salesforce connection in Integrations
            to load the operator directory.
          </div>
        </div>
      </div>
    );
  }

  if (!current) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="display-md">User profile</h1>
          <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">
            No operator selected. Pick the Salesforce user whose identity should be recorded on
            Continuous Learning actions.
          </p>
        </div>
        <div className="card p-8 text-center">
          <div className="inline-flex w-12 h-12 rounded-full bg-zbrain-50 text-zbrain items-center justify-center text-xl mb-3">
            ?
          </div>
          <div className="text-base font-medium text-zbrain-ink">Pick an operator</div>
          <div className="text-sm text-zbrain-muted mt-1 max-w-md mx-auto">
            Use the avatar in the top right of the header to choose a Salesforce user. Promote,
            rollback, and retire endpoints require an operator on the rule-owner allow-list.
          </div>
          <button onClick={openPicker} className="btn-primary mt-4">
            Open operator picker
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="display-md">User profile</h1>
        <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">
          The Salesforce user whose identity is recorded on every Continuous Learning action you
          take in this workspace.
        </p>
      </div>

      <div className="card overflow-hidden">
        <div className="px-6 py-6 flex items-start gap-5 border-b border-zbrain-divider">
          <Avatar user={current} size="xl" ring />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-zbrain-ink leading-tight">{current.name}</h2>
              {current.is_rule_owner ? (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] uppercase tracking-[0.1em] font-semibold"
                  title={current.rule_owner_label || "Rule owner"}
                >
                  Rule owner
                </span>
              ) : (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 text-[10px] uppercase tracking-[0.1em] font-semibold"
                  title="Read-only on promote, rollback, retire"
                >
                  Read-only on learning actions
                </span>
              )}
            </div>
            {current.email && (
              <div className="text-sm text-zbrain-muted mt-1">{current.email}</div>
            )}
            {current.is_rule_owner && current.rule_owner_label && (
              <div className="text-xs text-emerald-800 mt-2 font-medium">
                {current.rule_owner_label}
              </div>
            )}
          </div>
          <div className="shrink-0">
            <button onClick={openPicker} className="btn-secondary text-xs">
              Switch user
            </button>
          </div>
        </div>

        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 px-6 py-5">
          <ProfileField label="Display name" value={current.name} />
          <ProfileField label="Email" value={current.email || "-"} />
          <ProfileField
            label="Salesforce username"
            value={current.username || "-"}
            mono
            wide
          />
          <ProfileField label="Salesforce user id" value={current.id} mono />
          <ProfileField
            label="Role"
            value={current.is_rule_owner ? "Rule owner" : "Read-only on learning actions"}
          />
          {current.is_rule_owner && current.rule_owner_label && (
            <ProfileField label="Rule owner label" value={current.rule_owner_label} />
          )}
        </dl>
      </div>

      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-zbrain-divider">
          <h2 className="text-sm font-semibold">Identity source</h2>
        </div>
        <div className="px-5 py-4 text-sm text-zbrain-muted leading-relaxed space-y-2">
          <p>
            User name and email are sourced from Salesforce. Edit your profile in Salesforce; changes
            appear here within 60 seconds.
          </p>
          <p>
            To act as a different user, open the avatar in the top right of the header and pick a
            Salesforce user. The selection persists locally until you sign out.
          </p>
        </div>
      </div>
    </div>
  );
}

function ProfileField({
  label,
  value,
  mono,
  wide,
}: {
  label: string;
  value: string;
  mono?: boolean;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : ""}>
      <dt className="text-[10px] uppercase tracking-[0.12em] text-zbrain-muted font-semibold">
        {label}
      </dt>
      <dd
        className={[
          "mt-1 text-sm text-zbrain-ink break-all",
          mono ? "font-mono text-[12.5px]" : "",
        ].join(" ")}
      >
        {value}
      </dd>
    </div>
  );
}
