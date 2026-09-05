// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react';
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
  const listTasks = vi.fn();
  const listTasksPage = vi.fn(async (query: { limit?: number; offset?: number }) => {
    const items = await listTasks(query) as TaskRead[];
    return {
      items,
      total: items.length,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0,
    };
  });
  return {
    ...original,
    workbenchApi: {
      ...original.workbenchApi,
      getAccess: vi.fn(),
      getDashboard: vi.fn(),
      listProjects: vi.fn(),
      listEmployees: vi.fn(),
      listTasks,
      listTasksPage,
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

const globalAdmin: EnterpriseAuthUser = {
  ...manager,
  id: 'user-global-admin',
  username: 'global-admin',
  display_name: '全局管理员',
  role: 'admin',
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

const globalAdminAccess: WorkbenchAccessRead = {
  tenant_id: globalAdmin.tenant_id,
  user_id: globalAdmin.id,
  business_role: 'admin',
  directory_scope: 'all',
  can_create_project: true,
  can_view_all: true,
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
        limit: 50,
        offset: 0,
      });
    });
    await user.selectOptions(screen.getByLabelText('项目筛选'), project.id);
    await waitFor(() => {
      expect(workbenchApi.listTasks).toHaveBeenLastCalledWith({
        tenant_id: manager.tenant_id,
        scope: 'department',
        status: 'review',
        project_id: project.id,
        limit: 50,
        offset: 0,
      });
    });
  });

  it('paginates task results in 50-row pages and resets to the first page when filters change', async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) =>
      task('backlog', `task-page-${index + 1}`, `分页任务 ${index + 1}`),
    );
    const secondPage = Array.from({ length: 50 }, (_, index) =>
      task('backlog', `task-page-${index + 51}`, `分页任务 ${index + 51}`),
    );
    const boundary = task('backlog', 'task-page-101', '分页任务 101');
    const filtered = [task('done', 'task-filtered-done', '筛选后的已完成任务')];
    vi.mocked(workbenchApi.listTasksPage)
      .mockResolvedValueOnce({ items: firstPage, total: 101, limit: 50, offset: 0 })
      .mockResolvedValueOnce({ items: secondPage, total: 101, limit: 50, offset: 50 })
      .mockResolvedValueOnce({ items: [boundary], total: 101, limit: 50, offset: 100 })
      .mockResolvedValueOnce({ items: filtered, total: 1, limit: 50, offset: 0 });
    const user = userEvent.setup();
    renderTasks();

    expect(await screen.findByText('分页任务 50')).toBeTruthy();
    expect(screen.queryByText('分页任务 101')).toBeNull();
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: manager.tenant_id,
      scope: 'department',
      status: undefined,
      project_id: undefined,
      limit: 50,
      offset: 0,
    });
    expect(screen.getByRole('button', { name: '上一页' })).toHaveProperty('disabled', true);

    await user.click(screen.getByRole('button', { name: '下一页' }));
    expect(await screen.findByText('分页任务 100')).toBeTruthy();
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: manager.tenant_id,
      scope: 'department',
      status: undefined,
      project_id: undefined,
      limit: 50,
      offset: 50,
    });
    expect(screen.getByRole('button', { name: '下一页' })).toHaveProperty('disabled', false);
    expect(screen.getByRole('button', { name: '上一页' })).toHaveProperty('disabled', false);

    await user.click(screen.getByRole('button', { name: '下一页' }));
    expect(await screen.findByText('分页任务 101')).toBeTruthy();
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: manager.tenant_id,
      scope: 'department',
      status: undefined,
      project_id: undefined,
      limit: 50,
      offset: 100,
    });
    expect(screen.getByRole('button', { name: '下一页' })).toHaveProperty('disabled', true);

    await user.selectOptions(screen.getByLabelText('状态筛选'), 'done');
    expect(await screen.findByText('筛选后的已完成任务')).toBeTruthy();
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: manager.tenant_id,
      scope: 'department',
      status: 'done',
      project_id: undefined,
      limit: 50,
      offset: 0,
    });
    expect(screen.getByRole('button', { name: '上一页' })).toHaveProperty('disabled', true);
  });

  it('shows dependencies, acceptance, delivery, reviewer feedback, and chronological events', async () => {
    const user = userEvent.setup();
    renderTasks();

    await user.click(await screen.findByRole('button', { name: '打开任务 整理用户研究' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('高优先级')).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看依赖 完成定位研究' })).toBeTruthy();
    expect(screen.getByText('交付内容通过负责人验收')).toBeTruthy();
    expect(screen.getAllByText('已完成第一版交付')).toHaveLength(1);
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

  it('distinguishes assigned people with restricted directory details from unassigned roles', async () => {
    const restrictedAssigneeId = 'user-private-assignee';
    const restrictedReviewerId = 'user-private-reviewer';
    const restricted = task('in_progress', 'task-private-people', '受限人员任务', {
      assignee_user_id: restrictedAssigneeId,
      reviewer_user_id: restrictedReviewerId,
    });
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([]);
    vi.mocked(workbenchApi.listTasks).mockResolvedValueOnce([restricted]);
    vi.mocked(workbenchApi.getTask).mockResolvedValueOnce(restricted);
    const user = userEvent.setup();
    renderTasks();

    await user.click(await screen.findByRole('button', { name: '打开任务 受限人员任务' }));
    let dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('负责人信息受限')).toBeTruthy();
    expect(within(dialog).getByText('审核人信息受限')).toBeTruthy();
    expect(dialog.textContent).not.toContain(restrictedAssigneeId);
    expect(dialog.textContent).not.toContain(restrictedReviewerId);
    expect(within(dialog).queryByText('未分配员工')).toBeNull();
    cleanup();

    const unassigned = task('backlog', 'task-unassigned-people', '真实未分配任务', {
      assignee_user_id: null,
      reviewer_user_id: null,
    });
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([]);
    vi.mocked(workbenchApi.listTasks).mockResolvedValueOnce([unassigned]);
    vi.mocked(workbenchApi.getTask).mockResolvedValueOnce(unassigned);
    renderTasks();

    await user.click(await screen.findByRole('button', { name: '打开任务 真实未分配任务' }));
    dialog = await screen.findByRole('dialog');
    expect(within(dialog).getAllByText('未分配员工')).toHaveLength(2);
    expect(within(dialog).queryByText('负责人信息受限')).toBeNull();
    expect(within(dialog).queryByText('审核人信息受限')).toBeNull();
  });

  it('lets an assignee start, comment, update progress, and submit referenced artifacts with fresh versions', async () => {
    const backlog = task('backlog', 'task-personal', '整理访谈结论', { version: 2 });
    const inProgressV3 = { ...backlog, status: 'in_progress' as const, version: 3 };
    const inProgressV4 = { ...inProgressV3, version: 4 };
    const inProgressV5 = { ...inProgressV4, progress: 70, version: 5 };
    const reviewV6 = { ...inProgressV5, status: 'review' as const, version: 6 };
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([backlog])
      .mockResolvedValueOnce([inProgressV3])
      .mockResolvedValueOnce([inProgressV4])
      .mockResolvedValueOnce([inProgressV5])
      .mockResolvedValueOnce([reviewV6]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(backlog)
      .mockResolvedValueOnce(inProgressV3)
      .mockResolvedValueOnce(inProgressV4)
      .mockResolvedValueOnce(inProgressV5)
      .mockResolvedValueOnce(reviewV6);
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

    await user.clear(screen.getByLabelText('任务进度'));
    await user.type(screen.getByLabelText('任务进度'), '70');
    await user.click(screen.getByRole('button', { name: '保存进度' }));
    expect(workbenchApi.updateTask).toHaveBeenLastCalledWith(backlog.id, {
      tenant_id: member.tenant_id,
      version: 4,
      progress: 70,
    });

    await user.type(screen.getByLabelText('成果摘要'), '形成洞察报告与原始记录');
    await user.type(screen.getByLabelText('成果引用 1'), 'https://example.com/research-report');
    await user.click(screen.getByRole('button', { name: '添加成果引用' }));
    await user.type(screen.getByLabelText('成果引用 2'), 'resource-user-research-42');
    await user.click(screen.getByRole('button', { name: '提交成果' }));
    expect(workbenchApi.submitTask).toHaveBeenCalledWith(backlog.id, {
      tenant_id: member.tenant_id,
      version: 5,
      result_summary: '形成洞察报告与原始记录',
      artifact_refs: ['https://example.com/research-report', 'resource-user-research-42'],
    });

    expect(workbenchApi.getTask).toHaveBeenCalledTimes(5);
    expect(workbenchApi.listTasks).toHaveBeenCalledTimes(5);
  });

  it('refreshes the latest progress and version after a 409 progress conflict', async () => {
    const initial = task('in_progress', 'task-progress-conflict', '进度冲突任务', {
      version: 9,
      progress: 40,
    });
    const fresh = { ...initial, version: 10, progress: 65 };
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([initial])
      .mockResolvedValueOnce([fresh]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(fresh);
    vi.mocked(workbenchApi.updateTask).mockRejectedValueOnce(
      new ApiError(409, '{"detail":"Task version conflict"}', 'Conflict'),
    );
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: '打开任务 进度冲突任务' }));
    const progress = screen.getByLabelText('任务进度');
    await user.clear(progress);
    await user.type(progress, '80');
    await user.click(screen.getByRole('button', { name: '保存进度' }));

    expect(workbenchApi.updateTask).toHaveBeenCalledWith(initial.id, {
      tenant_id: member.tenant_id,
      version: 9,
      progress: 80,
    });
    expect(await screen.findByText(/任务版本冲突，已刷新最新状态/)).toBeTruthy();
    expect(progress).toHaveProperty('value', '65');
    expect(screen.getByText('版本 10')).toBeTruthy();
  });

  it('shows prior artifact references and reuses them for a returned-task resubmission', async () => {
    const priorSubmission: WorkTaskEventRead = {
      ...eventComment,
      id: 'event-result-prior',
      event_type: 'result_submitted',
      payload: {
        result_summary: '第一版成果',
        artifact_refs: ['https://example.com/first-report', 'resource-first-42'],
      },
      created_at: '2026-09-03T09:30:00Z',
    };
    const returned = task('in_progress', 'task-returned-result', '重新提交研究成果', {
      version: 6,
      result_summary: '第一版成果',
      events: [priorSubmission, eventReturned],
    });
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([returned]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(returned);
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: '打开任务 重新提交研究成果' }));
    expect(screen.getByRole('link', { name: 'https://example.com/first-report' })).toHaveProperty('href', 'https://example.com/first-report');
    expect(screen.getByText('resource-first-42')).toBeTruthy();
    expect(screen.getByLabelText('成果摘要')).toHaveProperty('value', '第一版成果');
    expect(screen.getByLabelText('成果引用 1')).toHaveProperty('value', 'https://example.com/first-report');
    expect(screen.getByLabelText('成果引用 2')).toHaveProperty('value', 'resource-first-42');
    await user.click(screen.getByRole('button', { name: '重新提交成果' }));

    expect(workbenchApi.submitTask).toHaveBeenCalledWith(returned.id, {
      tenant_id: member.tenant_id,
      version: 6,
      result_summary: '第一版成果',
      artifact_refs: ['https://example.com/first-report', 'resource-first-42'],
    });
  });

  it('localizes artifact-reference labels and placeholders for assistive technology', async () => {
    const localized = task('in_progress', 'task-artifact-i18n', 'English artifact task');
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([localized]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(localized);
    window.localStorage.setItem('staffdeck_locale', 'en-US');
    const user = userEvent.setup();
    renderTasks(member);

    const taskTitle = await screen.findByText(localized.title);
    const taskButton = taskTitle.closest('button');
    expect(taskButton).toBeTruthy();
    await user.click(taskButton!);

    const reference = await screen.findByLabelText('Deliverable reference 1');
    expect(reference.hasAttribute('data-i18n-ignore')).toBe(false);
    expect(reference.getAttribute('aria-label')).toBe('Deliverable reference 1');
    expect(reference.getAttribute('placeholder')).toBe('https://… or resource ID');
  });

  it.each(['review', 'done', 'canceled'] as const)('does not expose execution mutations for %s tasks', async (status) => {
    const immutable = task(status, `task-no-execute-${status}`, `${status} 不可执行`);
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(memberAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([immutable]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(immutable);
    const user = userEvent.setup();
    renderTasks(member);

    await user.click(await screen.findByRole('button', { name: `打开任务 ${immutable.title}` }));
    await screen.findByRole('dialog');
    expect(screen.queryByLabelText('任务进度')).toBeNull();
    expect(screen.queryByRole('button', { name: '保存进度' })).toBeNull();
    expect(screen.queryByRole('button', { name: /提交成果/ })).toBeNull();
    expect(screen.queryByRole('button', { name: '开始任务' })).toBeNull();
    if (status === 'done' || status === 'canceled') {
      expect(screen.queryByLabelText('添加评论')).toBeNull();
      expect(screen.queryByRole('button', { name: '发表评论' })).toBeNull();
    }
    cleanup();
  });

  it('opens a task detail from the supported task_id query parameter', async () => {
    const linked = task('review', 'task-linked-review', '驾驶舱直达任务');
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([linked]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(linked);

    renderTasks(manager, `/enterprise/tasks?task_id=${linked.id}`);

    expect(await screen.findByRole('dialog', { name: linked.title })).toBeTruthy();
    expect(workbenchApi.getTask).toHaveBeenCalledWith(linked.id, manager.tenant_id);
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

  it('allows only the assignee to execute, even when another user owns or manages the project', async () => {
    const delegated = task('in_progress', 'task-delegated-execution', '不能代替成员执行', {
      assignee_user_id: member.id,
      reviewer_user_id: 'user-other-reviewer',
    });
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([delegated]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(delegated);
    let user = userEvent.setup();
    renderTasks(manager);

    await user.click(await screen.findByRole('button', { name: '打开任务 不能代替成员执行' }));
    expect(screen.queryByLabelText('任务进度')).toBeNull();
    expect(screen.queryByRole('button', { name: '保存进度' })).toBeNull();
    expect(screen.queryByRole('button', { name: /提交成果/ })).toBeNull();
    cleanup();

    const adminDelegated = task('backlog', 'task-admin-delegated', '管理员也不能代执行', {
      assignee_user_id: member.id,
    });
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(globalAdminAccess);
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([adminDelegated]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(adminDelegated);
    user = userEvent.setup();
    renderTasks(globalAdmin);

    await user.click(await screen.findByRole('button', { name: '打开任务 管理员也不能代执行' }));
    expect(screen.queryByRole('button', { name: '开始任务' })).toBeNull();
    cleanup();

    const managedReview = task('review', 'task-managed-review', '管理者仍可审核', {
      assignee_user_id: member.id,
      reviewer_user_id: 'user-other-reviewer',
    });
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(managerAccess);
    vi.mocked(workbenchApi.listTasks).mockResolvedValue([managedReview]);
    vi.mocked(workbenchApi.getTask).mockResolvedValue(managedReview);
    user = userEvent.setup();
    renderTasks(manager);

    await user.click(await screen.findByRole('button', { name: '打开任务 管理者仍可审核' }));
    expect(screen.getByRole('button', { name: '审核通过' })).toBeTruthy();
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
    const artifactRef = screen.getByLabelText('成果引用 1');
    await user.type(summary, '不能丢失的成果摘要');
    await user.type(artifactRef, 'resource-draft-must-survive');
    await user.click(screen.getByRole('button', { name: '提交成果' }));
    expect(await screen.findByText(/操作被拒绝/)).toBeTruthy();
    expect(summary).toHaveProperty('value', '不能丢失的成果摘要');
    expect(artifactRef).toHaveProperty('value', 'resource-draft-must-survive');
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
    vi.mocked(workbenchApi.updateTask).mockResolvedValue(
      task('in_progress', 'task-today', '整理今日访谈', { progress: 55, version: 3 }),
    );
    vi.mocked(workbenchApi.submitTask).mockResolvedValue(
      task('review', 'task-today', '整理今日访谈', { version: 4 }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
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

  it('loads more than 100 personal tasks in 50-row pages without dropping the boundary task', async () => {
    const firstPage = Array.from({ length: 50 }, (_, index) =>
      task('in_progress', `task-my-work-page-${index + 1}`, `我的分页任务 ${index + 1}`),
    );
    const secondPage = Array.from({ length: 50 }, (_, index) =>
      task('in_progress', `task-my-work-page-${index + 51}`, `我的分页任务 ${index + 51}`),
    );
    const boundary = {
      ...task('in_progress', 'task-my-work-page-101', '我的分页任务 101'),
      title: '第 101 条待处理任务',
    };
    vi.mocked(workbenchApi.listTasksPage)
      .mockResolvedValueOnce({ items: firstPage, total: 101, limit: 50, offset: 0 })
      .mockResolvedValueOnce({ items: secondPage, total: 101, limit: 50, offset: 50 })
      .mockResolvedValueOnce({ items: [boundary], total: 101, limit: 50, offset: 100 });
    const user = userEvent.setup();
    renderMyWork();

    expect(await screen.findByText('我的分页任务 50')).toBeTruthy();
    expect(screen.queryByText('第 101 条待处理任务')).toBeNull();
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: member.tenant_id,
      scope: 'mine',
      limit: 50,
      offset: 0,
    });

    await user.click(screen.getByRole('button', { name: '加载更多任务' }));
    expect((await screen.findAllByText('我的分页任务 100')).length).toBeGreaterThan(0);
    expect(screen.queryByText('第 101 条待处理任务')).toBeNull();
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: member.tenant_id,
      scope: 'mine',
      limit: 50,
      offset: 50,
    });

    await user.click(screen.getByRole('button', { name: '加载更多任务' }));
    expect((await screen.findAllByText('第 101 条待处理任务')).length).toBeGreaterThan(0);
    expect(workbenchApi.listTasksPage).toHaveBeenLastCalledWith({
      tenant_id: member.tenant_id,
      scope: 'mine',
      limit: 50,
      offset: 100,
    });
    expect(screen.queryByRole('button', { name: '加载更多任务' })).toBeNull();
  });

  it('wires progress and artifact resubmission through My Work with current task versions', async () => {
    const initial = task('in_progress', 'task-my-work-execution', '完成执行闭环', {
      progress: 20,
      version: 2,
    });
    const progressed = { ...initial, progress: 55, version: 3 };
    const submitted = { ...progressed, status: 'review' as const, version: 4 };
    vi.mocked(workbenchApi.listTasks)
      .mockResolvedValueOnce([initial])
      .mockResolvedValueOnce([progressed])
      .mockResolvedValueOnce([submitted]);
    vi.mocked(workbenchApi.getTask)
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(progressed)
      .mockResolvedValueOnce(submitted);
    const user = userEvent.setup();
    renderMyWork();

    await user.click(await screen.findByRole('button', { name: '打开任务 完成执行闭环' }));
    await user.clear(screen.getByLabelText('任务进度'));
    await user.type(screen.getByLabelText('任务进度'), '55');
    await user.click(screen.getByRole('button', { name: '保存进度' }));
    expect(workbenchApi.updateTask).toHaveBeenCalledWith(initial.id, {
      tenant_id: member.tenant_id,
      version: 2,
      progress: 55,
    });

    await user.type(screen.getByLabelText('成果摘要'), '执行闭环已完成');
    await user.type(screen.getByLabelText('成果引用 1'), 'asset-my-work-1');
    await user.click(screen.getByRole('button', { name: '提交成果' }));
    expect(workbenchApi.submitTask).toHaveBeenCalledWith(initial.id, {
      tenant_id: member.tenant_id,
      version: 3,
      result_summary: '执行闭环已完成',
      artifact_refs: ['asset-my-work-1'],
    });
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
    vi.useFakeTimers();
    const boundaryTask = task('in_progress', 'task-shanghai-boundary', '上海零点边界任务', {
      due_date: '2026-09-04',
    });
    vi.mocked(workbenchApi.listTasks).mockResolvedValueOnce([boundaryTask]);

    renderMyWork({
      now: new Date('2026-09-04T16:30:00.000Z'),
      timeZone: 'Asia/Shanghai',
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(
      within(screen.getByRole('article', { name: '已逾期' })).getByText('1'),
    ).toBeTruthy();
    const card = screen.getByRole('button', { name: '打开任务 上海零点边界任务' });
    expect(within(card).getByText('2026-09-04').className).toContain('text-[#d20b0b]');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('updates My Work KPIs and cards across local midnight without remounting', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-04T15:59:30.000Z'));
    const boundaryTask = task('in_progress', 'task-live-midnight', '跨午夜任务', {
      due_date: '2026-09-04',
    });
    vi.mocked(workbenchApi.listTasks).mockResolvedValueOnce([boundaryTask]);

    const view = renderMyWork({ timeZone: 'Asia/Shanghai' });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(within(screen.getByRole('article', { name: '已逾期' })).getByText('0')).toBeTruthy();
    const card = screen.getByRole('button', { name: '打开任务 跨午夜任务' });
    expect(within(card).getByText('2026-09-04').className).not.toContain('text-[#d20b0b]');

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });

    expect(within(screen.getByRole('article', { name: '已逾期' })).getByText('1')).toBeTruthy();
    expect(within(card).getByText('2026-09-04').className).toContain('text-[#d20b0b]');
    view.unmount();
    expect(vi.getTimerCount()).toBe(0);
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
