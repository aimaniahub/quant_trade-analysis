'use client';

interface LoadingBannerProps {
  active: boolean;
  label?: string;
  progress?: number | null;
  detail?: string;
  variant?: 'default' | 'overlay';
}

/**
 * Dynamic loading indicator driven by real fetch state (not fake timers alone).
 */
export default function LoadingBanner({
  active,
  label = 'Loading…',
  progress = null,
  detail,
  variant = 'default',
}: LoadingBannerProps) {
  if (!active) return null;

  const pct =
    progress != null && Number.isFinite(progress)
      ? Math.max(0, Math.min(100, progress))
      : null;

  const bar = (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
          </span>
          <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-700 dark:text-zinc-200 truncate">
            {label}
          </span>
        </div>
        {pct != null && (
          <span className="text-[10px] font-mono font-bold text-zinc-500">{Math.round(pct)}%</span>
        )}
      </div>
      <div className="h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full bg-gradient-to-r from-blue-600 via-cyan-500 to-emerald-500 transition-all duration-300 ${
            pct == null ? 'w-1/3 animate-pulse' : ''
          }`}
          style={pct != null ? { width: `${pct}%` } : undefined}
        />
      </div>
      {detail && (
        <p className="text-[10px] text-zinc-500 font-medium">{detail}</p>
      )}
    </div>
  );

  if (variant === 'overlay') {
    return (
      <div className="absolute inset-0 z-20 flex items-start justify-center bg-black/40 backdrop-blur-[2px] p-4 rounded-xl">
        <div className="w-full max-w-md mt-8 p-4 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 shadow-xl">
          {bar}
        </div>
      </div>
    );
  }

  return (
    <div className="mb-4 p-3 rounded-xl border border-blue-500/20 bg-blue-500/5">
      {bar}
    </div>
  );
}
