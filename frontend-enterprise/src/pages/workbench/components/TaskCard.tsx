import { CalendarDays, GitBranch, UserRoundCheck } from 'lucide-react';

import type { EmployeeRead, ProjectRead, TaskRead } from '@/types/workbench';

import { taskStatusLabel, taskStatusTone } from '../workbenchModel';
import { isTaskOverdue } from '../workbenchDate';
import EmployeeBadgeContainer from './EmployeeBadgeContainer';

export type TaskCardProps = {
  task: TaskRead;
  project?: ProjectRead;
  assignee?: EmployeeRead;
  onOpen: (taskId: string) => void;
  now?: Date;
  timeZone?: string;
};

const PRIORITY_LABEL: Record<TaskRead['priority'], string> = {
  low: '低优先级',
  normal: '普通',
  high: '高优先级',
  urgent: '紧急',
};

const TONE_CLASS = {
  blue: 'bg-[#eaf2ff] text-[#1a71ff]',
  orange: 'bg-[#fff4dd] text-[#a65f00]',
  green: 'bg-[#e9f7ef] text-[#018434]',
  red: 'bg-[#fce7e7] text-[#d20b0b]',
  gray: 'bg-[#f2f3f7] text-[#596176]',
};

export default function TaskCard({
  task,
  project,
  assignee,
  onOpen,
  now,
  timeZone,
}: TaskCardProps) {
  const statusTone = taskStatusTone(task.status);
  const dueTone = isTaskOverdue(task.due_date, task.status, { now, timeZone })
    ? 'text-[#d20b0b]'
    : 'text-[#757f9c]';

  return (
    <article className="overflow-hidden rounded-[13px] border border-[#e8ebf2] bg-white shadow-[0_5px_18px_rgba(24,30,46,0.035)]">
      <button
        type="button"
        aria-label={`打开任务 ${task.title}`}
        onClick={() => onOpen(task.id)}
        className="block w-full px-[14px] py-[13px] text-left outline-none transition-colors hover:bg-[#fafbfe] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#1a71ff]"
      >
        <div className="flex items-start justify-between gap-[8px]">
          <span className={`rounded-full px-[7px] py-[3px] text-[9px] font-medium ${TONE_CLASS[statusTone]}`}>
            {taskStatusLabel(task.status)}
          </span>
          <span className={task.priority === 'urgent' ? 'text-[9px] font-semibold text-[#d20b0b]' : 'text-[9px] text-[#858b9c]'}>
            {PRIORITY_LABEL[task.priority]}
          </span>
        </div>
        <h3 className="mt-[9px] mb-0 text-[13px] font-semibold leading-[19px] text-[#24262d]">{task.title}</h3>
        {task.description && (
          <p className="mt-[5px] mb-0 line-clamp-2 text-[10px] leading-[16px] text-[#757f9c]">{task.description}</p>
        )}
        <p className="mt-[9px] mb-0 truncate text-[10px] text-[#9aa1b3]">{project?.name || '项目'}</p>
        <div className="mt-[11px] h-[5px] overflow-hidden rounded-full bg-[#edf0f5]" role="progressbar" aria-label={`${task.title}进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={task.progress}>
          <span className="block h-full rounded-full bg-[#1a71ff]" style={{ width: `${Math.min(100, Math.max(0, task.progress))}%` }} />
        </div>
        <div className="mt-[11px] space-y-[7px] border-t border-[#f0f2f6] pt-[10px]">
          <div className="flex items-center justify-between gap-[8px] text-[9px]">
            <span className={`flex min-w-0 items-center gap-[4px] ${dueTone}`}>
              <CalendarDays className="size-[10px] shrink-0" aria-hidden="true" />
              {task.due_date || '截止日期待定'}
            </span>
            {task.dependencies.length > 0 && (
              <span className="flex shrink-0 items-center gap-[3px] text-[#858b9c]">
                <GitBranch className="size-[10px]" aria-hidden="true" />
                {task.dependencies.length} 项依赖
              </span>
            )}
          </div>
          {assignee ? (
            <EmployeeBadgeContainer employee={assignee} compact subtitle="真人负责人" />
          ) : (
            <span className="flex items-center gap-[6px] text-[10px] text-[#a65f00]">
              <UserRoundCheck className="size-[12px]" aria-hidden="true" />
              {task.assignee_user_id ? '真人员工信息受限' : '待人工指派'}
            </span>
          )}
        </div>
      </button>
    </article>
  );
}
