// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
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
  WorkTaskEventRead,
} from '@/types/workbench';

import WorkbenchDashboardPage from './WorkbenchDashboardPage';
import { workbenchApi } from './workbenchApi';

vi.mock('./workbenchApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('./workbenchApi')>();
  return {
    ...original,
    workbenchApi: {
      ...original.workbenchApi,
      getDashboard: vi.fn(),
      listEmployees: vi.fn(),
    },
  };
});

const currentUser: EnterpriseAuthUser = {
  id: 'user-ceo',
  tenant_id: 'tenant-demo',
  username: 'ceo',
  display_name: '陈总',
  role: 'member',
};

const baseEmployee: EmployeeRead = {
  id: 'employee-ceo',
  tenant_id: 'tenant-demo',
  user_id: 'user-ceo',
  username: 'ceo',
  display_name: '陈总',
  avatar_url: null,
  employee_no: 'E001',
  department_id: 'department-product',
  job_title: 'CEO',
  business_role: 'ceo',
  level: 'P9',
  skills: ['经营管理'],
  capacity_percent: 80,
  daily_cost: 2400,
  manager_user_id: null,
  assistant_agent_id: null,
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const productEmployee: EmployeeRead = {
  ...baseEmployee,
  id: 'employee-product',
  user_id: 'user-product',
  username: 'product',
  display_name: '林珊',
  employee_no: 'E002',
  job_title: '产品经理',
  business_role: 'member',
  level: 'P6',
  skills: ['产品设计'],
  capacity_percent: 100,
  daily_cost: 1200,
};

const inactiveEmployee: EmployeeRead = {
  ...productEmployee,
  id: 'employee-former',
  user_id: 'user-former',
  username: 'former',
  display_name: '已停用员工',
  daily_cost: 10000,
  status: 'inactive',
};

const managerEmployee: EmployeeRead = {
  ...productEmployee,
  id: 'employee-manager',
  user_id: 'user-manager',
  username: 'manager',
  display_name: '部门经理',
  employee_no: 'E003',
  business_role: 'manager',
};

const project: ProjectRead = {
  id: 'project-launch',
  tenant_id: 'tenant-demo',
  name: '产品发布',
  objective: '按期完成新版发布',
  description: '跨部门发布项目',
  owner_user_id: 'user-ceo',
  department_id: 'department-product',
  status: 'active',
  health: 'at_risk',
  start_date: '2026-09-01',
  due_date: '2026-09-20',
  budget: 50000,
  version: 2,
  task_total: 4,
  task_done: 1,
  progress: 25,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const pendingTask: TaskRead = {
  id: 'task-review',
  tenant_id: 'tenant-demo',
  project_id: project.id,
  plan_id: 'plan-launch',
  parent_task_id: null,
  title: '确认发布清单',
  description: '复核所有上线项',
  required_role: '产品负责人',
  priority: 'high',
  status: 'review',
  assignee_user_id: 'user-product',
  reviewer_user_id: 'user-ceo',
  start_date: '2026-09-02',
  due_date: '2026-09-03',
  estimate_days: 2,
  progress: 90,
  acceptance_criteria: '清单完整',
  result_summary: '已整理',
  version: 3,
  dependencies: [],
  events: [],
  created_at: '2026-09-02T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
  completed_at: null,
};

const recentEvent: WorkTaskEventRead = {
  id: 'event-1',
  task_id: pendingTask.id,
  tenant_id: 'tenant-demo',
  actor_user_id: 'user-product',
  actor_type: 'human',
  event_type: 'task_submitted',
  payload: { result_summary: '已整理' },
  created_at: '2026-09-04T08:00:00Z',
};

const dashboard: DashboardRead = {
  tenant_id: 'tenant-demo',
  project_count: 3,
  task_counts: { backlog: 4, blocked: 1, in_progress: 2, review: 1, done: 5 },
  employee_count: 2,
  pending_review_count: 1,
  at_risk_project_count: 1,
  department_loads: [
    {
      user_id: 'user-product',
      department_id: 'department-product',
      capacity_percent: 100,
      active_task_count: 3,
      estimate_days: 6,
    },
  ],
  workload_rows: [
    {
      user_id: 'user-product',
      department_id: 'department-product',
      capacity_percent: 100,
      active_task_count: 3,
      estimate_days: 6,
    },
  ],
  pending_reviews: [pendingTask],
  at_risk_tasks: [pendingTask],
  project_summaries: [project],
  recent_events: [recentEvent],
};

function renderDashboard(user = currentUser) {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <WorkbenchDashboardPage currentUser={user} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('WorkbenchDashboardPage', () => {
  beforeEach(() => {
    vi.mocked(workbenchApi.getDashboard).mockResolvedValue(dashboard);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([
      baseEmployee,
      productEmployee,
      inactiveEmployee,
    ]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('shows persisted company metrics, reviews, workload, risks, and activity to a CEO', async () => {
    renderDashboard();

    expect(await screen.findByRole('heading', { level: 2, name: '公司运营概览' })).toBeTruthy();
    expect(screen.getByText('项目总数').parentElement?.textContent).toContain('3');
    expect(screen.getByText('待审核任务').parentElement?.textContent).toContain('1');
    expect(screen.getByText('团队日成本').parentElement?.textContent).toContain('¥3,600');
    expect(screen.getAllByText('确认发布清单').length).toBeGreaterThan(0);
    expect(screen.getAllByText('林珊').length).toBeGreaterThan(0);
    expect(screen.getByText('负载 6 人日 · 3 项进行中')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '风险提醒' })).toBeTruthy();
    expect(screen.getByText('林珊提交了任务')).toBeTruthy();
  });

  it('shows only personal work metrics to a member and never exposes global cost', async () => {
    const member: EnterpriseAuthUser = {
      id: 'user-product',
      tenant_id: 'tenant-demo',
      username: 'product',
      display_name: '林珊',
      role: 'member',
    };
    vi.mocked(workbenchApi.getDashboard).mockResolvedValue({
      ...dashboard,
      project_count: 1,
      employee_count: 1,
      pending_review_count: 0,
      task_counts: { in_progress: 2, review: 1 },
      pending_reviews: [],
      workload_rows: [dashboard.workload_rows[0]],
      department_loads: [dashboard.workload_rows[0]],
    });
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );

    renderDashboard(member);

    expect(await screen.findByRole('heading', { level: 2, name: '我的工作概览' })).toBeTruthy();
    expect(screen.getByText('我的进行中').parentElement?.textContent).toContain('2');
    expect(screen.getByText('待审核').parentElement?.textContent).toContain('1');
    expect(screen.queryByText('待提交')).toBeNull();
    expect(screen.queryByText('团队日成本')).toBeNull();
    expect(screen.queryByText('公司项目')).toBeNull();
  });

  it.each([
    {
      label: 'administrator',
      user: { ...currentUser, id: 'user-admin', username: 'admin', role: 'admin' as const },
      employees: [baseEmployee, productEmployee],
      recoveredHeading: '公司运营概览',
    },
    {
      label: 'CEO',
      user: currentUser,
      employees: [baseEmployee, productEmployee],
      recoveredHeading: '公司运营概览',
    },
    {
      label: 'manager',
      user: {
        ...currentUser,
        id: managerEmployee.user_id,
        username: managerEmployee.username,
        display_name: managerEmployee.display_name || managerEmployee.username,
      },
      employees: [managerEmployee, productEmployee],
      recoveredHeading: '部门运营概览',
    },
  ])('shows a retryable partial-data error when $label employee data fails', async ({
    user: authUser,
    employees: recoveredEmployees,
    recoveredHeading,
  }) => {
    vi.mocked(workbenchApi.listEmployees)
      .mockRejectedValueOnce(new Error('employee directory unavailable'))
      .mockResolvedValueOnce(recoveredEmployees);
    const user = userEvent.setup();

    renderDashboard(authUser);

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('工作台部分数据加载失败'),
    );
    expect(screen.queryByText('团队日成本')).toBeNull();
    expect(screen.queryByRole('heading', { name: '我的工作概览' })).toBeNull();
    expect(screen.queryByText('聚焦由你负责的真实工作与协作动态')).toBeNull();

    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByRole('heading', { name: recoveredHeading })).toBeTruthy();
  });

  it('renders useful empty states when persisted aggregates contain no work', async () => {
    vi.mocked(workbenchApi.getDashboard).mockResolvedValue({
      tenant_id: 'tenant-demo',
      project_count: 0,
      task_counts: {},
      employee_count: 0,
      pending_review_count: 0,
      at_risk_project_count: 0,
      department_loads: [],
      workload_rows: [],
      pending_reviews: [],
      at_risk_tasks: [],
      project_summaries: [],
      recent_events: [],
    });
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([]);

    renderDashboard({ ...currentUser, role: 'admin' });

    expect(await screen.findByText('还没有项目或任务数据')).toBeTruthy();
    expect(screen.getByText('暂无待审核任务')).toBeTruthy();
    expect(screen.getByText('暂无人员负载数据')).toBeTruthy();
    expect(screen.getByText('暂无风险任务')).toBeTruthy();
    expect(screen.getByText('暂无近期动态')).toBeTruthy();
  });

  it('renders loading, retryable error, and permission-denied states', async () => {
    const pending = new Promise<DashboardRead>(() => undefined);
    vi.mocked(workbenchApi.getDashboard).mockReturnValueOnce(pending);
    const view = renderDashboard();
    expect(screen.getByRole('status', { name: '工作台加载中' })).toBeTruthy();
    view.unmount();

    vi.mocked(workbenchApi.getDashboard)
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce(dashboard);
    const user = userEvent.setup();
    renderDashboard();
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('工作台加载失败'));
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByRole('heading', { level: 2, name: '公司运营概览' })).toBeTruthy();
    cleanup();

    vi.mocked(workbenchApi.getDashboard).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Forbidden"}', 'Forbidden'),
    );
    renderDashboard();
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('无权查看工作台'));
  });
});
