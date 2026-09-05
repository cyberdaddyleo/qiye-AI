// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { I18nProvider } from '@/i18n';
import type {
  DashboardRead,
  EmployeeRead,
  ProjectRead,
  TaskRead,
  TaskStatus,
  WorkTaskEventRead,
  WorkbenchAccessRead,
} from '@/types/workbench';

import MyWorkPage from './MyWorkPage';
import TasksPage from './TasksPage';
import { workbenchApi } from './workbenchApi';

vi.mock('./workbenchApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('./workbenchApi')>();
  return {
    ...original,
    workbenchApi: {
      ...original.workbenchApi,
      getAccess: vi.fn(),
      getDashboard: vi.fn(),
      listProjects: vi.fn(),
      listEmployees: vi.fn(),
      listTasks: vi.fn(),
      getTask: vi.fn(),
      updateTask: vi.fn(),
      commentTask: vi.fn(),
      submitTask: vi.fn(),
      reviewTask: vi.fn(),
    },
  };
});

const manager: EnterpriseAuthUser = {
  id: 'user-manager',
  tenant_id: 'tenant-demo',
  username: 'manager',
  display_name: '周经理',
  role: 'member',
};

const member: EnterpriseAuthUser = {
  id: 'user-product',
  tenant_id: 'tenant-demo',
  username: 'linshan',
  display_name: '林珊',
  role: 'member',
};

const managerAccess: WorkbenchAccessRead = {
  tenant_id: manager.tenant_id,
  user_id: manager.id,
  business_role: 'manager',
  directory_scope: 'department',
  can_create_project: true,
  can_view_all: false,
  managed_department_ids: ['department-product'],
};

const memberAccess: WorkbenchAccessRead = {
  tenant_id: member.tenant_id,
  user_id: member.id,
  business_role: 'member',
  directory_scope: 'self',
  can_create_project: false,
  can_view_all: false,
  managed_department_ids: [],
};

const project: ProjectRead = {
  id: 'project-launch',
  tenant_id: manager.tenant_id,
  name: '新品发布',
  objective: '在九月完成新品发布',
  description: '跨职能发布项目',
  owner_user_id: manager.id,
  department_id: 'department-product',
  status: 'active',
  health: 'at_risk',
  start_date: '2026-09-01',
  due_date: '2026-09-30',
  budget: 50000,
  version: 1,
  task_total: 6,
  task_done: 1,
  progress: 17,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const externalProject: ProjectRead = {
  ...project,
  id: 'project-design',
  owner_user_id: 'user-design-owner',
  department_id: 'department-design',
  name: '设计系统',
};

const productEmployee: EmployeeRead = {
  id: 'employee-product',
  tenant_id: member.tenant_id,
  user_id: member.id,
  username: member.username,
  display_name: member.display_name || null,
  avatar_url: null,
  employee_no: 'E002',
  department_id: 'department-product',
  job_title: '产品经理',
  business_role: 'member',
  level: 'P6',
  skills: ['用户研究'],
  capacity_percent: 80,
  daily_cost: 1200,
  manager_user_id: manager.id,
  assistant_agent_id: 'agent-helper',
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const managerEmployee: EmployeeRead = {
  ...productEmployee,
  id: 'employee-manager',
  user_id: manager.id,
  username: manager.username,
  display_name: manager.display_name || null,
  employee_no: 'E001',
  job_title: '产品负责人',
  business_role: 'manager',
  capacity_percent: 70,
  manager_user_id: null,
};

function task(
  status: TaskStatus,
  id = `task-${status}`,
  title = `${status} 任务`,
  overrides: Partial<TaskRead> = {},
): TaskRead {
  return {
    id,
    tenant_id: member.tenant_id,
    project_id: project.id,
    plan_id: 'plan-launch',
    parent_task_id: null,
    title,
    description: '推进新品发布工作',
    required_role: '产品经理',
    priority: status === 'blocked' ? 'urgent' : 'high',
    status,
    assignee_user_id: member.id,
    reviewer_user_id: manager.id,
    start_date: '2026-09-02',
    due_date: status === 'done' ? '2026-09-03' : '2026-09-08',
    estimate_days: 2,
    progress: status === 'done' ? 100 : status === 'review' ? 90 : 30,
    acceptance_criteria: '交付内容通过负责人验收',
    result_summary: status === 'review' || status === 'done' ? '已完成第一版交付' : null,
    version: 2,
    dependencies: [],
    events: [],
    created_at: '2026-09-02T08:00:00Z',
    updated_at: '2026-09-04T08:00:00Z',
    completed_at: status === 'done' ? '2026-09-04T08:00:00Z' : null,
    ...overrides,
  };
}

const doneDependency = task('done', 'task-dependency', '完成定位研究');
const eventStarted: WorkTaskEventRead = {
  id: 'event-started',
  task_id: 'task-in_progress',
  tenant_id: member.tenant_id,
  actor_user_id: member.id,
  actor_type: 'human',
  event_type: 'task_started',
  payload: {},
  created_at: '2026-09-03T08:00:00Z',
};
const eventComment: WorkTaskEventRead = {
  id: 'event-comment',
  task_id: 'task-in_progress',
  tenant_id: member.tenant_id,
  actor_user_id: member.id,
  actor_type: 'human',
  event_type: 'comment_added',
  payload: { comment: '已完成访谈，准备整理结论' },
  created_at: '2026-09-03T09:00:00Z',
};
const eventReturned: WorkTaskEventRead = {
  id: 'event-returned',
  task_id: 'task-in_progress',
  tenant_id: member.tenant_id,
  actor_user_id: manager.id,
  actor_type: 'human',
  event_type: 'review_returned',
  payload: { comment: '请补充关键数据来源' },
  created_at: '2026-09-03T10:00:00Z',
};

const detailedTask = task('in_progress', 'task-in_progress', '整理用户研究', {
  result_summary: '已完成第一版交付',
  dependencies: [doneDependency.id],
  events: [eventReturned, eventStarted, eventComment],
});

const allStatuses: TaskRead[] = [
  task('backlog', 'task-backlog', '准备访谈提纲'),
  task('blocked', 'task-blocked', '发布上线', { dependencies: [doneDependency.id] }),
  detailedTask,
  task('review', 'task-review', '审核发布清单'),
  doneDependency,
  task('canceled', 'task-canceled', '旧版发布方案'),
];

const dashboard: DashboardRead = {
  tenant_id: member.tenant_id,
  project_count: 1,
  task_counts: { backlog: 1, blocked: 1, in_progress: 1, review: 1, done: 1 },
  employee_count: 1,
  pending_review_count: 1,
  at_risk_project_count: 1,
  department_loads: [],
  workload_rows: [
    {
      user_id: member.id,
      department_id: 'department-product',
      capacity_percent: 80,
      active_task_count: 3,
      estimate_days: 6,
    },
  ],
  pending_reviews: [task('review', 'task-review', '审核发布清单')],
  at_risk_tasks: [task('in_progress', 'task-overdue', '补齐竞品数据', { due_date: '2026-09-01' })],
  project_summaries: [project],
  recent_events: [eventComment],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function renderTasks(user: EnterpriseAuthUser = manager, path = '/enterprise/tasks') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <TasksPage currentUser={user} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

function renderMyWork(options: { now?: Date; timeZone?: string } = {}) {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <MyWorkPage currentUser={member} {...options} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('TasksPage', () => {
  beforeEach(() => {
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(managerAccess);
    vi.mocked(workbenchApi.listProjects).mockResolvedValue([project]);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([productEmployee, managerEmployee]);
    vi.mocked(workbenchApi.listTasks).mockResolvedValue(allStatuses);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(detailedTask);
    vi.mocked(workbenchApi.updateTask).mockResolvedValue(detailedTask);
    vi.mocked(workbenchApi.commentTask).mockResolvedValue(detailedTask);
    vi.mocked(workbenchApi.submitTask).mockResolvedValue(task('review', detailedTask.id, detailedTask.title));
    vi.mocked(workbenchApi.reviewTask).mockResolvedValue(task('done', 'task-review', '审核发布清单'));
    vi.mocked(workbenchApi.getDashboard).mockResolvedValue(dashboard);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it('renders every Kanban status with semantic labels and sends server-side filters', async () => {
    const user = userEvent.setup();
    renderTasks();

    for (const label of ['待办', '已阻塞', '进行中', '待审核', '已完成', '已取消']) {
      expect(await screen.findByRole('region', { name: `${label}任务列` })).toBeTruthy();
    }
    expect(screen.getByText('准备访谈提纲')).toBeTruthy();
    expect(screen.getByText('发布上线')).toBeTruthy();
    expect(screen.getByRole('region', { name: '任务看板' }).classList.contains('overflow-x-auto')).toBe(true);

    await user.selectOptions(screen.getByLabelText('状态筛选'), 'review');
    await waitFor(() => {
      expect(workbenchApi.listTasks).toHaveBeenLastCalledWith({
        tenant_id: manager.tenant_id,
        scope: 'department',
        status: 'review',
        project_id: undefined,
      });
    });
    await user.selectOptions(screen.getByLabelText('项目筛选'), project.id);
    await waitFor(() => {
      expect(workbenchApi.listTasks).toHaveBeenLastCalledWith({
        tenant_id: manager.tenant_id,
        scope: 'department',
        status: 'review',
        project_id: project.id,
      });
    });
  });

  it('shows dependencies, acceptance, delivery, reviewer feedback, and chronological events', async () => {
    const user = userEvent.setup();
    renderTasks();

    await user.click(await screen.findByRole('button', { name: '打开任务 整理用户研究' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('高优先级')).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看依赖 完成定位研究' })).toBeTruthy();
    expect(screen.getByText('交付内容通过负责人验收')).toBeTruthy();
    expect(screen.getByText('已完成第一版交付')).toBeTruthy();
    expect(screen.getAllByText('请补充关键数据来源')).toHaveLength(2);

    const timeline = screen.getByRole('list', { name: '任务动态' });
    const content = timeline.textContent || '';
    expect(content.indexOf('开始了任务')).toBeLessThan(content.indexOf('添加了评论'));
    expect(content.indexOf('添加了评论')).toBeLessThan(content.indexOf('退回了任务'));

    const sheet = document.querySelector<HTMLElement>('[data-slot="sheet-content"]');
    expect(sheet?.classList.contains('data-[side=right]:sm:max-w-[680px]')).toBe(true);
    expect(sheet?.classList.contains('data-[side=right]:max-[640px]:w-full')).toBe(true);
    expect(sheet?.classList.contains('max-[640px]:max-w-none')).toBe(true);
  });

  it('lets an assignee start, comment, and submit while refetching detail and list after each mutation', async () => {
    const backlog = task('backlog', 'task-personal', '整理访谈结论', { version: 2 });
    const inProgressV3 = { ...backlog, status: 'in_progress' as const, version: 3 };
    const inProgressV4 = { ...inProgressV3, version: 4 };
    const reviewV5 = { ...inProgressV4, status: 'review' as const, version: 5 };
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([backlog])
      .mockResolvedValueOnce([inProgressV3])
      .mockResolvedValueOnce([inProgressV4])
      .mockResolvedValueOnce([reviewV5]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(backlog)
      .mockResolvedValueOnce(inProgressV3)
      .mockResolvedValueOnce(inProgressV4)
      .mockResolvedValueOnce(reviewV5);
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: '打开任务 整理访谈结论' }));
    await user.click(await screen.findByRole('button', { name: '开始任务' }));
    expect(workbenchApi.updateTask).toHaveBeenCalledWith(backlog.id, {
      tenant_id: member.tenant_id,
      version: 2,
      status: 'in_progress',
    });
    expect(await screen.findByRole('button', { name: '提交成果' })).toBeTruthy();

    await user.type(screen.getByLabelText('添加评论'), '访谈数据已经整理完毕');
    await user.click(screen.getByRole('button', { name: '发表评论' }));
    expect(workbenchApi.commentTask).toHaveBeenCalledWith(backlog.id, {
      tenant_id: member.tenant_id,
      version: 3,
      comment: '访谈数据已经整理完毕',
    });
    expect(screen.getByLabelText('添加评论')).toHaveProperty('value', '');

    await user.type(screen.getByLabelText('成果摘要'), '形成洞察报告与原始记录');
    await user.click(screen.getByRole('button', { name: '提交成果' }));
    expect(workbenchApi.submitTask).toHaveBeenCalledWith(backlog.id, {
      tenant_id: member.tenant_id,
      version: 4,
      result_summary: '形成洞察报告与原始记录',
      artifact_refs: [],
    });

    expect(workbenchApi.getTask).toHaveBeenCalledTimes(4);
    expect(workbenchApi.listTasks).toHaveBeenCalledTimes(4);
  });

  it('lets a manager approve or return submitted work with a reviewer comment', async () => {
    const reviewTask = task('review', 'task-review-action', '验收用户研究', { version: 7 });
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([reviewTask]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(reviewTask);
    const user = userEvent.setup();
    renderTasks();

    await user.click(await screen.findByRole('button', { name: '打开任务 验收用户研究' }));
    await user.type(screen.getByLabelText('审核意见'), '交付符合验收标准');
    await user.click(screen.getByRole('button', { name: '审核通过' }));
    expect(workbenchApi.reviewTask).toHaveBeenCalledWith(reviewTask.id, {
      tenant_id: manager.tenant_id,
      version: 7,
      verdict: 'approve',
      comment: '交付符合验收标准',
    });
    cleanup();

    vi.mocked(workbenchApi.listTasks).mockResolvedValue([reviewTask]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(reviewTask);
    renderTasks();
    await user.click(await screen.findByRole('button', { name: '打开任务 验收用户研究' }));
    await user.type(screen.getByLabelText('审核意见'), '请补充来源链接');
    await user.click(screen.getByRole('button', { name: '退回重做' }));
    expect(workbenchApi.reviewTask).toHaveBeenLastCalledWith(reviewTask.id, {
      tenant_id: manager.tenant_id,
      version: 7,
      verdict: 'rework',
      comment: '请补充来源链接',
    });
  });

  it('does not turn an external-department manager assignment into unrelated task powers', async () => {
    const cases: Array<{
      value: TaskRead;
      absent: string;
      present?: string;
    }> = [
      {
        value: task('backlog', 'task-external-reviewer-backlog', '外部门待办', {
          project_id: externalProject.id,
          assignee_user_id: member.id,
          reviewer_user_id: manager.id,
        }),
        absent: '开始任务',
      },
      {
        value: task('in_progress', 'task-external-reviewer-progress', '外部门执行中', {
          project_id: externalProject.id,
          assignee_user_id: member.id,
          reviewer_user_id: manager.id,
        }),
        absent: '提交成果',
      },
      {
        value: task('review', 'task-external-assignee-review', '外部门待审核', {
          project_id: externalProject.id,
          assignee_user_id: manager.id,
          reviewer_user_id: member.id,
        }),
        absent: '审核通过',
      },
      {
        value: task('in_progress', 'task-external-assignee-progress', '外部门本人执行', {
          project_id: externalProject.id,
          assignee_user_id: manager.id,
          reviewer_user_id: member.id,
        }),
        absent: '审核通过',
        present: '提交成果',
      },
      {
        value: task('review', 'task-external-reviewer-review', '外部门本人审核', {
          project_id: externalProject.id,
          assignee_user_id: member.id,
          reviewer_user_id: manager.id,
        }),
        absent: '提交成果',
        present: '审核通过',
      },
    ];

    for (const current of cases) {
      vi.mocked(workbenchApi.listProjects).mockResolvedValue([externalProject]);
      vi.mocked(workbenchApi.listTasks).mockResolvedValue([current.value]);
      vi.mocked(workbenchApi.getTask).mockResolvedValue(current.value);
      const user = userEvent.setup();
      renderTasks(manager);
      await user.click(await screen.findByRole('button', { name: `打开任务 ${current.value.title}` }));
      await screen.findByRole('dialog');
      expect(screen.queryByRole('button', { name: current.absent })).toBeNull();
      if (current.present) {
        expect(screen.getByRole('button', { name: current.present })).toBeTruthy();
      }
      cleanup();
    }
  });

  it('refreshes authoritative server state and explains a 409 version conflict', async () => {
    const backlog = task('backlog', 'task-conflict', '冲突任务', { version: 2 });
    const fresh = { ...backlog, version: 3, title: '服务端最新任务标题' };
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([backlog])
      .mockResolvedValueOnce([fresh]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(backlog)
      .mockResolvedValueOnce(fresh);
    vi.mocked(workbenchApi.updateTask).mockRejectedValueOnce(
      new ApiError(409, '{"detail":"Task version conflict"}', 'Conflict'),
    );
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: '打开任务 冲突任务' }));
    await user.click(await screen.findByRole('button', { name: '开始任务' }));

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('任务版本冲突，已刷新最新状态'),
    );
    expect(await screen.findByRole('heading', { name: '服务端最新任务标题' })).toBeTruthy();
    expect(workbenchApi.getTask).toHaveBeenCalledTimes(2);
    expect(workbenchApi.listTasks).toHaveBeenCalledTimes(2);
  });

  it('reconciles an unknown mutation result and preserves the comment draft', async () => {
    const initial = task('in_progress', 'task-response-lost', '响应丢失任务', { version: 4 });
    const reconciled = {
      ...initial,
      version: 5,
      events: [
        ...initial.events,
        { ...eventComment, id: 'event-reconciled', task_id: initial.id },
      ],
    };
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([initial])
      .mockResolvedValueOnce([reconciled]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(reconciled);
    vi.mocked(workbenchApi.commentTask).mockRejectedValueOnce(new Error('response lost'));
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: '打开任务 响应丢失任务' }));
    const input = screen.getByLabelText('添加评论');
    await user.type(input, '保留这条重要评论');
    await user.click(screen.getByRole('button', { name: '发表评论' }));

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('任务操作结果未知'),
    );
    expect(input).toHaveProperty('value', '保留这条重要评论');
    expect(workbenchApi.getTask).toHaveBeenCalledTimes(2);
    expect(workbenchApi.listTasks).toHaveBeenCalledTimes(2);
  });

  it('keeps result and review drafts on 403 and 409 failures', async () => {
    const personal = task('in_progress', 'task-submit-forbidden', '提交被拒任务', { version: 2 });
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([personal]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(personal);
    vi.mocked(workbenchApi.submitTask).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Forbidden"}', 'Forbidden'),
    );
    let user = userEvent.setup();
    renderTasks(member);
    await user.click(await screen.findByRole('button', { name: '打开任务 提交被拒任务' }));
    const summary = screen.getByLabelText('成果摘要');
    await user.type(summary, '不能丢失的成果摘要');
    await user.click(screen.getByRole('button', { name: '提交成果' }));
    expect(await screen.findByText(/操作被拒绝/)).toBeTruthy();
    expect(summary).toHaveProperty('value', '不能丢失的成果摘要');
    cleanup();

    const submitted = task('review', 'task-review-conflict-draft', '审核冲突任务', {
      version: 7,
      reviewer_user_id: manager.id,
    });
    const latest = { ...submitted, version: 8 };
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(managerAccess);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([productEmployee, managerEmployee]);
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([submitted])
      .mockResolvedValueOnce([latest]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(submitted)
      .mockResolvedValueOnce(latest);
    vi.mocked(workbenchApi.reviewTask).mockRejectedValueOnce(
      new ApiError(409, '{"detail":"Conflict"}', 'Conflict'),
    );
    user = userEvent.setup();
    renderTasks(manager);
    await user.click(await screen.findByRole('button', { name: '打开任务 审核冲突任务' }));
    const reviewDraft = screen.getByLabelText('审核意见');
    await user.type(reviewDraft, '需要保留的审核意见');
    await user.click(screen.getByRole('button', { name: '审核通过' }));
    expect(await screen.findByText(/任务版本冲突/)).toBeTruthy();
    expect(reviewDraft).toHaveProperty('value', '需要保留的审核意见');
  });

  it('keeps blocked task execution disabled until dependencies finish', async () => {
    const blocked = task('blocked', 'task-blocked-action', '等待依赖的任务', {
      dependencies: [doneDependency.id],
    });
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([blocked, doneDependency]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(blocked);
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: '打开任务 等待依赖的任务' }));

    expect(await screen.findByRole('button', { name: '开始任务' })).toHaveProperty('disabled', true);
    expect(screen.getByText('依赖任务完成后才能开始')).toBeTruthy();
    expect(workbenchApi.updateTask).not.toHaveBeenCalled();
  });

  it('shows loading, empty, retryable error, and 403 task states', async () => {
    const pendingTasks = deferred<TaskRead[]>();
    vi.mocked(workbenchApi.listTasks).mockReturnValueOnce(pendingTasks.promise);
    renderTasks();
    expect(screen.getByRole('status', { name: '任务加载中' })).toBeTruthy();
    pendingTasks.resolve([]);
    expect(await screen.findByRole('heading', { name: '当前筛选下没有任务' })).toBeTruthy();
    cleanup();

    vi.mocked(workbenchApi.listTasks).mockRejectedValueOnce(new Error('offline'));
    renderTasks();
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('任务加载失败'),
    );
    cleanup();

    vi.mocked(workbenchApi.listTasks).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Cannot view department tasks"}', 'Forbidden'),
    );
    renderTasks();
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('无权查看任务中心'),
    );
  });
});

describe('MyWorkPage', () => {
  beforeEach(() => {
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.getDashboard).mockResolvedValue(dashboard);
    vi.mocked(workbenchApi.listProjects).mockResolvedValue([project]);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([
      task('in_progress', 'task-today', '整理今日访谈', { due_date: '2026-09-05' }),
      task('in_progress', 'task-reviewer-only-progress', '仅由我审核的执行中任务', {
        assignee_user_id: manager.id,
        reviewer_user_id: member.id,
        due_date: '2026-09-01',
      }),
      task('review', 'task-pending-review', '等待我审核', {
        assignee_user_id: manager.id,
        reviewer_user_id: member.id,
      }),
      task('blocked', 'task-overdue', '补齐竞品数据', { due_date: '2026-09-01' }),
    ]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(
      task('in_progress', 'task-today', '整理今日访谈', { due_date: '2026-09-05' }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('shows role-aware priorities, personal counts, submissions, collaboration, and workload', async () => {
    const user = userEvent.setup();
    renderMyWork();

    expect(await screen.findByRole('heading', { name: '林珊，今天先完成最重要的工作' })).toBeTruthy();
    expect(within(screen.getByRole('article', { name: '进行中' })).getByText('1')).toBeTruthy();
    expect(within(screen.getByRole('article', { name: '待审核' })).getByText('1')).toBeTruthy();
    expect(within(screen.getByRole('article', { name: '已逾期' })).getByText('1')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '今日优先' })).toBeTruthy();
    expect(screen.getAllByText('整理今日访谈')).toHaveLength(2);
    expect(screen.queryByText('仅由我审核的执行中任务')).toBeNull();
    expect(screen.getByRole('heading', { name: '待我审核' })).toBeTruthy();
    expect(screen.getByText('等待我审核')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '待提交成果' })).toBeTruthy();
    expect(screen.getByText('林珊添加了评论')).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: '可用容量' }).getAttribute('aria-valuenow')).toBe('80');

    await user.click(screen.getByRole('button', { name: '打开任务 整理今日访谈' }));
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByRole('button', { name: '提交成果' })).toBeTruthy();
  });

  it('shows a useful empty state and distinguishes permission failures', async () => {
    vi.mocked(workbenchApi.listTasks).mockResolvedValueOnce([]);
    vi.mocked(workbenchApi.getDashboard).mockResolvedValueOnce({
      ...dashboard,
      task_counts: {},
      recent_events: [],
      workload_rows: [],
    });
    renderMyWork();
    expect(await screen.findByRole('heading', { name: '今天没有待处理工作' })).toBeTruthy();
    cleanup();

    vi.mocked(workbenchApi.getAccess).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Forbidden"}', 'Forbidden'),
    );
    renderMyWork();
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('无权查看员工工作台'),
    );
  });

  it('shares the injected Shanghai business date with My Work and task cards', async () => {
    const boundaryTask = task('in_progress', 'task-shanghai-boundary', '上海零点边界任务', {
      due_date: '2026-09-04',
    });
    vi.mocked(workbenchApi.listTasks).mockResolvedValueOnce([boundaryTask]);

    renderMyWork({
      now: new Date('2026-09-04T16:30:00.000Z'),
      timeZone: 'Asia/Shanghai',
    });

    expect(
      within(await screen.findByRole('article', { name: '已逾期' })).getByText('1'),
    ).toBeTruthy();
    const card = screen.getByRole('button', { name: '打开任务 上海零点边界任务' });
    expect(within(card).getByText('2026-09-04').className).toContain('text-[#d20b0b]');
  });

  it('reconciles a 5xx mutation result in My Work and preserves its draft', async () => {
    const initial = task('in_progress', 'task-my-work-uncertain', '工作台响应未知', {
      due_date: '2026-09-05',
    });
    const reconciled = { ...initial, version: initial.version + 1 };
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([initial])
      .mockResolvedValueOnce([reconciled]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(reconciled);
    vi.mocked(workbenchApi.getDashboard)
      .mockResolvedValueOnce(dashboard)
      .mockResolvedValueOnce({ ...dashboard, recent_events: [] });
    vi.mocked(workbenchApi.commentTask).mockRejectedValueOnce(
      new ApiError(503, '{"detail":"Unavailable"}', 'Unavailable'),
    );
    const user = userEvent.setup();
    renderMyWork();

    await user.click(await screen.findByRole('button', { name: '打开任务 工作台响应未知' }));
    const input = screen.getByLabelText('添加评论');
    await user.type(input, '工作台也必须保留草稿');
    await user.click(screen.getByRole('button', { name: '发表评论' }));

    expect(await screen.findByText(/任务操作结果未知/)).toBeTruthy();
    expect(input).toHaveProperty('value', '工作台也必须保留草稿');
    expect(workbenchApi.getTask).toHaveBeenCalledTimes(2);
    expect(workbenchApi.listTasks).toHaveBeenCalledTimes(2);
    expect(workbenchApi.getDashboard).toHaveBeenCalledTimes(2);
  });
});
