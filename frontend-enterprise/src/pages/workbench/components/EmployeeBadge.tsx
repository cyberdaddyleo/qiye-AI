import EmployeeAvatar from '@/components/EmployeeAvatar';
import { DEFAULT_AVATAR_PRESET } from '@/employee';
import { cn } from '@/lib/utils';
import type { EmployeeRead } from '@/types/workbench';

export type EmployeeBadgeProps = {
  employee?: EmployeeRead | null;
  userId?: string;
  name?: string;
  subtitle?: string | null;
  compact?: boolean;
  className?: string;
};

export default function EmployeeBadge({
  employee,
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

  return (
    <span className={cn('flex min-w-0 items-center gap-[10px]', className)}>
      <EmployeeAvatar
        size={compact ? 30 : 38}
        radius={compact ? 9 : 11}
        profile={{
          avatarKind: employee?.avatar_url ? 'upload' : 'preset',
          avatarImage: employee?.avatar_url || '',
          avatarPreset: DEFAULT_AVATAR_PRESET,
          avatarText,
          avatarTone: 'blue',
        }}
      />
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-medium leading-[18px] text-[#24262d]">{displayName}</span>
        {supporting && (
          <span className="block truncate text-[11px] leading-[16px] text-[#858b9c]">{supporting}</span>
        )}
      </span>
    </span>
  );
}
