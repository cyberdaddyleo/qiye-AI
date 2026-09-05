import EmployeeAvatar from '@/components/EmployeeAvatar';
import { DEFAULT_AVATAR_PRESET } from '@/employee';
import { cn } from '@/lib/utils';
import type { EmployeeRead } from '@/types/workbench';

export type EmployeeBadgeProps = {
  employee?: EmployeeRead | null;
  avatarUrl?: string | null;
  userId?: string;
  name?: string;
  subtitle?: string | null;
  compact?: boolean;
  className?: string;
};

export default function EmployeeBadge({
  employee,
  avatarUrl,
  userId,
  name,
  subtitle,
  compact = false,
  className,
}: EmployeeBadgeProps) {
  const displayName = employee?.display_name || employee?.username || name || userId || '未分配员工';
  const supporting = subtitle === undefined
    ? employee?.job_title || employee?.employee_no || '真人员工'
    : subtitle;
  const avatarText = displayName.trim().slice(0, 1) || '员';
  const avatarSize = compact ? 30 : 38;
  const avatarRadius = compact ? 9 : 11;

  return (
    <span className={cn('flex min-w-0 items-center gap-[10px]', className)}>
      {avatarUrl ? (
        <EmployeeAvatar
          size={avatarSize}
          radius={avatarRadius}
          profile={{
            avatarKind: 'upload',
            avatarImage: avatarUrl,
            avatarPreset: DEFAULT_AVATAR_PRESET,
            avatarText,
            avatarTone: 'blue',
          }}
        />
      ) : (
        <span
          aria-label={`${avatarText}员工头像`}
          className="flex shrink-0 items-center justify-center bg-[#eaf2ff] font-semibold text-[#1a71ff]"
          style={{ width: avatarSize, height: avatarSize, borderRadius: avatarRadius }}
        >
          {avatarText}
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-medium leading-[18px] text-[#24262d]">{displayName}</span>
        {supporting && (
          <span className="block truncate text-[11px] leading-[16px] text-[#858b9c]">{supporting}</span>
        )}
      </span>
    </span>
  );
}
