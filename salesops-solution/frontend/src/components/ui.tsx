/**
 * Design system v2 primitives — Apple-style enterprise polish.
 *
 * Use these on any redesigned screen. Legacy `.card` / `.btn-primary` still
 * work for screens that haven't been touched yet.
 *
 * Three composable primitives:
 *
 *   <Surface>          — floating white card, soft shadow, no border, 14px radius.
 *                        The default container for any redesigned screen.
 *
 *   <Section>          — title + optional subtitle + optional action,
 *                        with consistent vertical rhythm. Goes inside a Surface.
 *
 *   <Field>            — label + value pair, label in eyebrow style (small caps,
 *                        10px tracking-wider), value in prominent ink.
 *
 * Plus refined buttons, pills, segmented controls. All accept className for
 * one-off overrides, but the defaults should fit 90% of cases.
 */
import { ReactNode, ButtonHTMLAttributes, AnchorHTMLAttributes } from "react";

/* ---------- Surface ---------- */

export function Surface({
  children,
  className = "",
  variant = "resting",
}: {
  children: ReactNode;
  className?: string;
  variant?: "resting" | "raised" | "floating";
}) {
  const surfaceClass =
    variant === "raised"
      ? "surface-raised"
      : variant === "floating"
      ? "surface-floating"
      : "surface";
  return <div className={`${surfaceClass} ${className}`}>{children}</div>;
}

/* ---------- Section (lives inside a Surface) ---------- */

export function Section({
  title,
  subtitle,
  action,
  children,
  className = "",
  padding = "default",
  divided = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
  padding?: "default" | "tight" | "loose" | "none";
  /** When true, draws a subtle divider between header and body. Use sparingly. */
  divided?: boolean;
}) {
  const padCls =
    padding === "none"
      ? ""
      : padding === "tight"
      ? "p-4"
      : padding === "loose"
      ? "p-7"
      : "p-5";
  const hasHeader = !!(title || subtitle || action);
  return (
    <section className={`${padCls} ${className}`}>
      {hasHeader && (
        <header className={`flex items-start gap-4 ${divided ? "pb-4 mb-4 border-b border-zbrain-divider/60" : children ? "mb-3" : ""}`}>
          <div className="flex-1 min-w-0">
            {title && <div className="section-title">{title}</div>}
            {subtitle && (
              <div className="text-[13px] text-zbrain-muted mt-0.5 leading-relaxed">{subtitle}</div>
            )}
          </div>
          {action && <div className="shrink-0 flex items-center gap-2">{action}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---------- Eyebrow (small-caps section label) ---------- */

export function Eyebrow({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={`eyebrow ${className}`}>{children}</div>;
}

/* ---------- Field (label-value pair) ---------- */

export function Field({
  label,
  value,
  helper,
  mono = false,
  emphasized = false,
  align = "left",
  className = "",
}: {
  label?: ReactNode;
  value: ReactNode;
  helper?: ReactNode;
  mono?: boolean;
  /** Use for the primary value on a card (slightly larger, bolder). */
  emphasized?: boolean;
  align?: "left" | "right";
  className?: string;
}) {
  const valueCls =
    (mono ? "font-mono " : "") +
    (emphasized
      ? "text-[18px] tracking-[-0.01em] font-semibold text-zbrain-ink"
      : "text-[14px] text-zbrain-ink") +
    (align === "right" ? " text-right tabular-nums" : "");
  return (
    <div className={className}>
      {label && <Eyebrow>{label}</Eyebrow>}
      <div className={`${valueCls} mt-0.5`}>
        {value === undefined || value === null || value === "" ? (
          <span className="text-zbrain-muted/60 italic">n/a</span>
        ) : (
          value
        )}
      </div>
      {helper && (
        <div className="text-[12px] text-zbrain-muted mt-1 leading-relaxed">{helper}</div>
      )}
    </div>
  );
}

/* ---------- Buttons ---------- */

type ButtonVariant = "primary" | "secondary" | "ghost" | "rose";

export function Button({
  variant = "secondary",
  className = "",
  iconBefore,
  iconAfter,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  iconBefore?: ReactNode;
  iconAfter?: ReactNode;
}) {
  const cls =
    variant === "primary"
      ? "btn-primary-v2"
      : variant === "ghost"
      ? "btn-ghost-v2"
      : variant === "rose"
      ? "btn-rose-v2"
      : "btn-secondary-v2";
  return (
    <button {...rest} className={`${cls} inline-flex items-center gap-1.5 ${className}`}>
      {iconBefore}
      {children}
      {iconAfter}
    </button>
  );
}

export function LinkButton({
  variant = "secondary",
  className = "",
  iconBefore,
  iconAfter,
  children,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant?: ButtonVariant;
  iconBefore?: ReactNode;
  iconAfter?: ReactNode;
}) {
  const cls =
    variant === "primary"
      ? "btn-primary-v2"
      : variant === "ghost"
      ? "btn-ghost-v2"
      : variant === "rose"
      ? "btn-rose-v2"
      : "btn-secondary-v2";
  return (
    <a {...rest} className={`${cls} inline-flex items-center gap-1.5 ${className}`}>
      {iconBefore}
      {children}
      {iconAfter}
    </a>
  );
}

/* ---------- Chip (refined pill) ---------- */

type ChipTone = "neutral" | "info" | "success" | "warning" | "danger" | "violet" | "emphasis";

const CHIP_TONES: Record<ChipTone, string> = {
  neutral: "bg-zbrain-surface text-zbrain-muted",
  info: "bg-sky-50 text-sky-800",
  success: "bg-emerald-50 text-emerald-800",
  warning: "bg-amber-50 text-amber-900",
  danger: "bg-rose-50 text-rose-800",
  violet: "bg-violet-50 text-violet-800",
  emphasis: "bg-zbrain-50 text-zbrain-700",
};

export function Chip({
  tone = "neutral",
  children,
  className = "",
  iconBefore,
}: {
  tone?: ChipTone;
  children: ReactNode;
  className?: string;
  iconBefore?: ReactNode;
}) {
  return (
    <span className={`chip ${CHIP_TONES[tone]} ${className}`}>
      {iconBefore && <span className="opacity-80">{iconBefore}</span>}
      {children}
    </span>
  );
}

/* ---------- Segmented control (iOS-style tab strip) ---------- */

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className = "",
}: {
  options: Array<{ value: T; label: ReactNode }>;
  value: T;
  onChange: (v: T) => void;
  className?: string;
}) {
  return (
    <div className={`segmented ${className}`} role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={`segmented-item ${o.value === value ? "segmented-item-active" : ""}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ---------- PageHeader (the consistent top of every redesigned page) ---------- */

export function PageHeader({
  title,
  subtitle,
  badges,
  actions,
  className = "",
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`flex items-start justify-between gap-6 ${className}`}>
      <div className="min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="display-md">{title}</h1>
          {badges && <div className="flex items-center gap-1.5">{badges}</div>}
        </div>
        {subtitle && (
          <p className="text-[14px] text-zbrain-muted mt-1.5 max-w-2xl leading-relaxed">{subtitle}</p>
        )}
      </div>
      {actions && <div className="shrink-0 flex items-center gap-2">{actions}</div>}
    </header>
  );
}

/* ---------- Subtle separator (rarely needed; let whitespace do the work) ---------- */

export function Separator({ className = "" }: { className?: string }) {
  return <div className={`h-px bg-zbrain-divider/60 ${className}`} />;
}
