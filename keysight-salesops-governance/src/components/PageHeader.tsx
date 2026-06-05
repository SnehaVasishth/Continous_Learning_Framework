export function PageHeader({
  title, subtitle, lastFetchedAt, error,
}: {
  title: string; subtitle?: string; lastFetchedAt: Date | null; error: string | null;
}) {
  return (
    <div className="flex items-end justify-between flex-wrap gap-2">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-zbrain-ink dark:text-zbrain-dark-ink">{title}</h1>
        {subtitle && <p className="text-sm text-zbrain-muted dark:text-zbrain-dark-muted mt-0.5">{subtitle}</p>}
      </div>
      <div className="text-[11px] text-zbrain-muted dark:text-zbrain-dark-muted">
        {error ? <span className="text-rose-700 dark:text-rose-400">Last fetch failed: {error}</span>
        : lastFetchedAt ? `Updated ${lastFetchedAt.toLocaleTimeString()} · auto-refreshes every 15s`
        : "Loading…"}
      </div>
    </div>
  );
}
