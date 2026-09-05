import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

type WorkbenchKpiTone = 'blue' | 'green' | 'orange' | 'red' | 'gray';

const TONE_CLASSES: Record<WorkbenchKpiTone, { icon: string; accent: string }> = {
  blue: { icon: 'bg-[#eaf2ff] text-[#1a71ff]', accent: 'bg-[#1a71ff]' },
  green: { icon: 'bg-[#e9f7ef] text-[#018434]', accent: 'bg-[#2cb360]' },
  orange: { icon: 'bg-[#fff4dd] text-[#a65f00]', accent: 'bg-[#f4a62a]' },
  red: { icon: 'bg-[#fce7e7] text-[#d20b0b]', accent: 'bg-[#e95858]' },
  gray: { icon: 'bg-[#f2f3f7] text-[#596176]', accent: 'bg-[#858b9c]' },
};

export type WorkbenchKpiProps = {
  label: string;
  value: ReactNode;
  supporting?: ReactNode;
  icon?: ReactNode;
  tone?: WorkbenchKpiTone;
};

export default function WorkbenchKpi({
  label,
  value,
  supporting,
  icon,
  tone = 'blue',
}: WorkbenchKpiProps) {
  const colors = TONE_CLASSES[tone];
  return (
    <article
      aria-label={label}
      className="relative min-w-0 overflow-hidden rounded-[16px] border border-[#edf0f5] bg-white p-[20px] shadow-[0_8px_24px_rgba(24,30,46,0.04)]"
    >
      <span className={cn('absolute inset-y-[18px] left-0 w-[3px] rounded-r-full', colors.accent)} />
      <div className="flex items-start justify-between gap-[12px]">
        <div className="min-w-0">
          <p className="m-0 text-[12px] font-medium leading-[18px] text-[#757f9c]">{label}</p>
          <p className="mt-[8px] mb-0 text-[26px] font-semibold leading-none tracking-[-0.02em] text-[#18181a]">
            {value}
          </p>
          {supporting != null && (
            <p className="mt-[8px] mb-0 text-[11px] leading-[17px] text-[#9aa1b3]">{supporting}</p>
          )}
        </div>
        {icon != null && (
          <span className={cn('flex size-[36px] shrink-0 items-center justify-center rounded-[11px]', colors.icon)} aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
    </article>
  );
}
