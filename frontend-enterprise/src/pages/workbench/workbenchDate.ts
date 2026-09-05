import type { TaskStatus } from '@/types/workbench';

export type BusinessDateOptions = {
  now?: Date;
  timeZone?: string;
};

export function businessDateKey({
  now = new Date(),
  timeZone,
}: BusinessDateOptions = {}): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    ...(timeZone ? { timeZone } : {}),
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const values = Object.fromEntries(
    parts
      .filter((part) => part.type === 'year' || part.type === 'month' || part.type === 'day')
      .map((part) => [part.type, part.value]),
  );
  return `${values.year}-${values.month}-${values.day}`;
}

export function isTaskOverdue(
  dueDate: string | null,
  status: TaskStatus,
  options: BusinessDateOptions = {},
): boolean {
  return status !== 'done'
    && status !== 'canceled'
    && Boolean(dueDate && dueDate < businessDateKey(options));
}
