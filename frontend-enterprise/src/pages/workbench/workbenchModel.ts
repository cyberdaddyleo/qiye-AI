import type {
  ProjectRead,
  TaskRead,
  TaskStatus,
  WorkloadRow,
} from '@/types/workbench';

export type WorkbenchStatusTone = 'blue' | 'orange' | 'green' | 'red' | 'gray';

export const WORKBENCH_TASK_STATUSES = [
  'backlog',
  'blocked',
  'in_progress',
  'review',
  'done',
  'canceled',
] as const satisfies readonly TaskStatus[];

const TASK_STATUS_PRESENTATION: Record<
  TaskStatus,
  { label: string; tone: WorkbenchStatusTone }
> = {
  backlog: { label: '待办', tone: 'gray' },
  blocked: { label: '已阻塞', tone: 'red' },
  in_progress: { label: '进行中', tone: 'blue' },
  review: { label: '待审核', tone: 'orange' },
  done: { label: '已完成', tone: 'green' },
  canceled: { label: '已取消', tone: 'gray' },
};

export function taskStatusLabel(status: TaskStatus): string {
  return TASK_STATUS_PRESENTATION[status].label;
}

export function taskStatusTone(status: TaskStatus): WorkbenchStatusTone {
  return TASK_STATUS_PRESENTATION[status].tone;
}

export function groupTasksByStatus(tasks: readonly TaskRead[]): Record<TaskStatus, TaskRead[]> {
  const groups: Record<TaskStatus, TaskRead[]> = {
    backlog: [],
    blocked: [],
    in_progress: [],
    review: [],
    done: [],
    canceled: [],
  };
  tasks.forEach((task) => groups[task.status].push(task));
  return groups;
}

export function projectProgress(project: Pick<ProjectRead, 'task_done' | 'task_total'>): number;
export function projectProgress(taskDone: number, taskTotal: number): number;
export function projectProgress(
  projectOrDone: Pick<ProjectRead, 'task_done' | 'task_total'> | number,
  totalArgument?: number,
): number {
  const taskDone = typeof projectOrDone === 'number' ? projectOrDone : projectOrDone.task_done;
  const taskTotal = typeof projectOrDone === 'number'
    ? totalArgument ?? 0
    : projectOrDone.task_total;
  if (!Number.isFinite(taskDone) || !Number.isFinite(taskTotal) || taskTotal <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((taskDone / taskTotal) * 100)));
}

export function formatWorkload(value: number | Pick<WorkloadRow, 'estimate_days'>): string {
  const raw = typeof value === 'number' ? value : value.estimate_days;
  const days = Number.isFinite(raw) && raw > 0 ? Math.round(raw * 10) / 10 : 0;
  return `${days} 人日`;
}
