import EmployeeBadge, { type EmployeeBadgeProps } from './EmployeeBadge';
import useEmployeeAvatarUrl from './useEmployeeAvatarUrl';

export type EmployeeBadgeContainerProps = Omit<EmployeeBadgeProps, 'avatarUrl'>;

export default function EmployeeBadgeContainer({
  employee,
  ...props
}: EmployeeBadgeContainerProps) {
  const avatarUrl = useEmployeeAvatarUrl(employee?.avatar_url);
  return <EmployeeBadge {...props} employee={employee} avatarUrl={avatarUrl} />;
}
