import { describe, expect, it } from 'vitest';

import type { WorkTask } from '@/types/workbench';

import {
  formatWorkload,
  groupTasksByStatus,
  projectProgress,
  taskStatusLabel,
  taskStatusTone,
} from './workbenchModel';

const baseTask: Omit<WorkTask, 'id' | 'status' | 'title'> = {
  tenant_id: 'tenant_demo',
  project_id: 'project-1',
  plan_id: null,
  parent_task_id: null,
  description: null,
  required_role: null,
  priority: 'normal',
  assignee_user_id: null,
  reviewer_user_id: null,
  start_date: null,
  due_date: null,
  estimate_days: null,
  progress: 0,
  acceptance_criteria: null,
  result_summary: null,
  version: 0,
  dependencies: [],
  events: [],
  created_at: '2026-09-04T00:00:00Z',
  updated_at: '2026-09-04T00:00:00Z',
  completed_at: null,
};

function task(id: string, status: WorkTask['status']): WorkTask {
  return { ...baseTask, id, title: id, status };
}

describe('workbench task presentation', () => {
  it('labels and tones every server-owned task status', () => {
    const statuses: WorkTask['status'][] = [
      'backlog',
      'blocked',
      'in_progress',
      'review',
      'done',
      'canceled',
    ];

    expect(statuses.map((status) => [
      status,
      taskStatusLabel(status),
      taskStatusTone(status),
    ])).toEqual([
      ['backlog', '待办', 'gray'],
      ['blocked', '已阻塞', 'red'],
      ['in_progress', '进行中', 'blue'],
      ['review', '待审核', 'orange'],
      ['done', '已完成', 'green'],
      ['canceled', '已取消', 'gray'],
    ]);
  });

  it('always returns all six task groups in workflow order', () => {
    const grouped = groupTasksByStatus([
      task('done-1', 'done'),
      task('backlog-1', 'backlog'),
      task('review-1', 'review'),
      task('blocked-1', 'blocked'),
      task('progress-1', 'in_progress'),
      task('canceled-1', 'canceled'),
      task('backlog-2', 'backlog'),
    ]);

    expect(Object.keys(grouped)).toEqual([
      'backlog',
      'blocked',
      'in_progress',
      'review',
      'done',
      'canceled',
    ]);
    expect(Object.fromEntries(
      Object.entries(grouped).map(([status, rows]) => [status, rows.map((row) => row.id)]),
    )).toEqual({
      backlog: ['backlog-1', 'backlog-2'],
      blocked: ['blocked-1'],
      in_progress: ['progress-1'],
      review: ['review-1'],
      done: ['done-1'],
      canceled: ['canceled-1'],
    });
  });
});

describe('workbench numeric presentation', () => {
  it('derives bounded project completion from returned task totals', () => {
    expect(projectProgress({ task_done: 3, task_total: 4 })).toBe(75);
    expect(projectProgress({ task_done: 0, task_total: 0 })).toBe(0);
    expect(projectProgress({ task_done: 7, task_total: 4 })).toBe(100);
  });

  it('formats finite workload estimates as compact person-days', () => {
    expect(formatWorkload(4.5)).toBe('4.5 人日');
    expect(formatWorkload(4)).toBe('4 人日');
    expect(formatWorkload(Number.NaN)).toBe('0 人日');
  });
});
