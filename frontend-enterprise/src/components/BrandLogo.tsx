import { cn } from '@/lib/utils';
import logoMark from '../assets/quantxy-logo-mark.png';

export type BrandLogoProps = {
  /** Hide the QuantXY wordmark and only render the logo mark. */
  markOnly?: boolean;
  /** Height of the logo mark in pixels. */
  markSize?: number;
  className?: string;
  /** Extra classes applied to the wordmark wrapper (e.g. to hide it responsively). */
  wordmarkClassName?: string;
};

/** QuantXY brand lockup: logo mark on the left and wordmark on the right. */
export default function BrandLogo({
  markOnly = false,
  markSize = 28,
  className,
  wordmarkClassName,
}: BrandLogoProps) {
  return (
    <span className={cn('flex items-center gap-[8px] overflow-hidden p-[4px]', className)}>
      <img
        src={logoMark}
        alt={markOnly ? 'QuantXY' : ''}
        className="shrink-0 object-contain"
        style={{ width: markSize * 1.5, height: markSize }}
      />
      {!markOnly && (
        <span className={cn('flex flex-col items-start gap-[3px] leading-none', wordmarkClassName)}>
          <strong className="text-[17px] font-semibold tracking-[0.08em] leading-none text-[#061633]">
            QuantXY
          </strong>
          <span className="text-[8px] tracking-[0.42em] leading-none text-[#061633]">
            量子星河
          </span>
        </span>
      )}
    </span>
  );
}
