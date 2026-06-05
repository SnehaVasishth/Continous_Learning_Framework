import { useEffect, useRef, useState } from "react";

import { SfUser, useOperator } from "../lib/operator";

/**
 * Header avatar picker for the "current operator" identity.
 *
 * Renders a round avatar button with the active user's initials in the top
 * right of the header. Clicking opens an anchored popover that lists every
 * Salesforce user from /api/sf-users, marks rule owners, and lets the
 * operator switch identity. The selection persists via OperatorContext
 * (localStorage), and learning actions read the current operator from there.
 *
 * Identity is live from Salesforce; this component does not write back, it
 * only chooses which SF user the audit trail should attribute actions to.
 */

const AVATAR_PALETTE: { bg: string; text: string; ring: string }[] = [
  { bg: "bg-emerald-100", text: "text-emerald-800", ring: "ring-emerald-300" },
  { bg: "bg-sky-100", text: "text-sky-800", ring: "ring-sky-300" },
  { bg: "bg-amber-100", text: "text-amber-800", ring: "ring-amber-300" },
  { bg: "bg-rose-100", text: "text-rose-800", ring: "ring-rose-300" },
  { bg: "bg-violet-100", text: "text-violet-800", ring: "ring-violet-300" },
  { bg: "bg-fuchsia-100", text: "text-fuchsia-800", ring: "ring-fuchsia-300" },
  { bg: "bg-teal-100", text: "text-teal-800", ring: "ring-teal-300" },
  { bg: "bg-indigo-100", text: "text-indigo-800", ring: "ring-indigo-300" },
];

export function avatarInitials(name: string | null | undefined): string {
  if (!name) return "?";
  const cleaned = name.trim();
  if (!cleaned) return "?";
  const parts = cleaned.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  const first = parts[0]![0] || "";
  const last = parts[parts.length - 1]![0] || "";
  return (first + last).toUpperCase();
}

export function avatarPalette(seed: string | null | undefined) {
  const key = seed || "";
  let h = 0;
  for (let i = 0; i < key.length; i++) {
    h = (h * 31 + key.charCodeAt(i)) >>> 0;
  }
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length]!;
}

export function Avatar({
  user,
  size = "md",
  ring = false,
}: {
  user: Pick<SfUser, "id" | "name"> | null;
  size?: "sm" | "md" | "lg" | "xl";
  ring?: boolean;
}) {
  const sizeClass =
    size === "sm"
      ? "h-7 w-7 text-[10px]"
      : size === "lg"
      ? "h-14 w-14 text-base"
      : size === "xl"
      ? "h-20 w-20 text-xl"
      : "h-9 w-9 text-xs";
  if (!user) {
    return (
      <span
        className={[
          sizeClass,
          "inline-flex items-center justify-center rounded-full bg-slate-100 text-slate-500 font-semibold select-none",
          ring ? "ring-2 ring-slate-200" : "",
        ].join(" ")}
        aria-hidden
      >
        ?
      </span>
    );
  }
  const palette = avatarPalette(user.id);
  return (
    <span
      className={[
        sizeClass,
        palette.bg,
        palette.text,
        "inline-flex items-center justify-center rounded-full font-semibold tracking-tight select-none",
        ring ? `ring-2 ${palette.ring}` : "",
      ].join(" ")}
      aria-hidden
    >
      {avatarInitials(user.name)}
    </span>
  );
}

export function OperatorPicker() {
  const { users, loaded, error, current, setCurrentId } = useOperator();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (ev: MouseEvent) => {
      if (!wrapperRef.current) return;
      if (!wrapperRef.current.contains(ev.target as Node)) setOpen(false);
    };
    const onEsc = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  // Allow the User profile page (or anyone else) to ask the avatar picker to
  // open. Dispatches a CustomEvent on window: window.dispatchEvent(new
  // CustomEvent("operator-picker:open")).
  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener("operator-picker:open", handler);
    return () => window.removeEventListener("operator-picker:open", handler);
  }, []);

  if (!loaded) {
    return (
      <span
        className="hidden md:inline-flex items-center text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted"
        title="Loading operator identity from Salesforce"
      >
        <span className="h-9 w-9 rounded-full bg-slate-100 dark:bg-zbrain-dark-elev2 animate-pulse" />
      </span>
    );
  }

  if (error) {
    return (
      <span
        className="hidden md:inline-flex items-center px-2 py-1 rounded-md bg-rose-50 text-rose-700 text-[11px] dark:bg-rose-500/10 dark:text-rose-300"
        title={error}
      >
        Operator unavailable
      </span>
    );
  }

  const others = users.filter((u) => u.id !== current?.id);
  const tooltip = current
    ? `Acting as ${current.name}${
        current.is_rule_owner
          ? " (rule owner, can promote / rollback / retire)"
          : " (read-only on learning actions)"
      }`
    : "Pick the operator whose identity will be recorded on Continuous Learning actions";

  return (
    <div ref={wrapperRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title={tooltip}
        aria-label={tooltip}
        aria-haspopup="menu"
        aria-expanded={open}
        className={[
          "relative inline-flex items-center justify-center rounded-full transition-shadow",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-zbrain/60 focus-visible:ring-offset-2",
          open ? "ring-2 ring-zbrain/50 ring-offset-2 dark:ring-offset-zbrain-dark-elev1" : "",
        ].join(" ")}
      >
        <Avatar user={current} size="md" />
        {current?.is_rule_owner && (
          <span
            className="absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full bg-emerald-500 ring-2 ring-white dark:ring-zbrain-dark-elev1"
            title={current.rule_owner_label || "Rule owner"}
            aria-hidden
          />
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[320px] max-w-[calc(100vw-2rem)] z-50">
          <div className="card overflow-hidden border border-zbrain-divider dark:border-zbrain-dark-divider shadow-xl bg-white dark:bg-zbrain-dark-elev1">
            <div className="px-5 pt-5 pb-4 flex flex-col items-center text-center">
              <Avatar user={current} size="xl" ring />
              <div className="mt-3 text-sm font-semibold text-zbrain-ink dark:text-zbrain-dark-ink">
                {current?.name || "No operator selected"}
              </div>
              {current?.email && (
                <div
                  className="text-[11.5px] text-zbrain-muted dark:text-zbrain-dark-muted truncate max-w-full"
                  title={current.email}
                >
                  {current.email}
                </div>
              )}
              {current?.is_rule_owner && (
                <span
                  className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[10px] uppercase tracking-[0.1em] font-semibold dark:bg-emerald-500/10 dark:text-emerald-300"
                  title={current.rule_owner_label || undefined}
                >
                  Rule owner
                </span>
              )}
            </div>

            <div className="px-3 pb-2 max-h-[40vh] overflow-auto border-t border-zbrain-divider dark:border-zbrain-dark-divider">
              <div className="px-2 pt-3 pb-1 text-[10px] uppercase tracking-[0.12em] text-zbrain-muted dark:text-zbrain-dark-muted font-semibold">
                Switch operator
              </div>
              <ul className="space-y-0.5">
                {current && (
                  <UserRow
                    user={current}
                    isCurrent
                    onSelect={() => setOpen(false)}
                  />
                )}
                {others.map((u) => (
                  <UserRow
                    key={u.id}
                    user={u}
                    isCurrent={false}
                    onSelect={() => {
                      setCurrentId(u.id);
                      setOpen(false);
                    }}
                  />
                ))}
                {users.length === 0 && (
                  <li className="px-2 py-3 text-xs text-zbrain-muted dark:text-zbrain-dark-muted">
                    No Salesforce users available.
                  </li>
                )}
              </ul>
            </div>

            <div className="border-t border-zbrain-divider dark:border-zbrain-dark-divider">
              <button
                onClick={() => {
                  setCurrentId(null);
                  setOpen(false);
                }}
                className="w-full flex items-center gap-2.5 px-5 py-3 text-sm text-rose-700 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-500/10 transition-colors"
              >
                <SignOutIcon />
                <span className="font-medium">Sign out</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function UserRow({
  user,
  isCurrent,
  onSelect,
}: {
  user: SfUser;
  isCurrent: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        onClick={onSelect}
        className={[
          "w-full flex items-center gap-3 px-2 py-2 rounded-md transition-colors text-left",
          isCurrent
            ? "bg-zbrain-50 dark:bg-zbrain-dark-elev2"
            : "hover:bg-zbrain-50/70 dark:hover:bg-zbrain-dark-elev2/70",
        ].join(" ")}
      >
        <Avatar user={user} size="sm" />
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-medium text-zbrain-ink dark:text-zbrain-dark-ink truncate">
            {user.name}
          </div>
          {user.email && (
            <div className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted truncate">
              {user.email}
            </div>
          )}
        </div>
        {user.is_rule_owner && (
          <span
            className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-[9px] uppercase tracking-[0.1em] font-semibold dark:bg-emerald-500/10 dark:text-emerald-300"
            title={user.rule_owner_label || "Rule owner"}
          >
            Rule owner
          </span>
        )}
        {isCurrent && <CheckIcon />}
      </button>
    </li>
  );
}

function CheckIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="shrink-0 text-zbrain"
      aria-hidden
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function SignOutIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  );
}
