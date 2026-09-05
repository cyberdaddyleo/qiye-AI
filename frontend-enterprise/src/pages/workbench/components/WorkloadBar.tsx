import { cn } from '@/lib/utils';

export type WorkloadBarProps = {
  value: number;
  label?: string;
  detail?: string;
  compact?: boolean;
};

function boundedPercent(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, Math.round(value)));
}

export default function WorkloadBar({
  value,
  label = '可用容量',
  detail,
  compact = false,
}: WorkloadBarProps) {
  const percent = boundedPercent(value);
  const indicator = percent < 40 ? 'bg-[#e95858]' : percent < 70 ? 'bg-[#f4a62a]' : 'bg-[#2cb360]';

  return (
    <div className="min-w-0" aria-label={`${label} ${percent}%`}>
      <div className="mb-[6px] flex items-center justify-between gap-[12px] text-[11px] leading-[16px]">
        <span className="truncate text-[#757f9c]">{detail || label}</span>
        <span className="shrink-0 font-medium text-[#464c5e]">{percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className={cn('w-full overflow-hidden rounded-full bg-[#edf0f5]', compact ? 'h-[5px]' : 'h-[7px]')}
      >
        <span
          className={cn('block h-full rounded-full transition-[width] duration-300', indicator)}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}
