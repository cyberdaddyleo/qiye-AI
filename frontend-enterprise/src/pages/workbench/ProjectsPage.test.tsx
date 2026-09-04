// @vitest-environment jsdom

import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { I18nProvider } from '@/i18n';
import type { DepartmentRead, EmployeeRead, ProjectRead } from '@/types/workbench';

import ProjectsPage from './ProjectsPage';
import { workbenchApi } from './workbenchApi';

vi.mock('./workbenchApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('./workbenchApi')>();
  return {
    ...original,
    workbenchApi: {
      ...original.workbenchApi,
      listProjects: vi.fn(),
      listDepartments: vi.fn(),
      listEmployees: vi.fn(),
      createProject: vi.fn(),
    },
  };
});

const admin: EnterpriseAuthUser = {
  id: 'user-admin',
  tenant_id: 'tenant-demo',
  username: 'admin',
  display_name: '管理员',
  role: 'admin',
};

const department: DepartmentRead = {
  id: 'department-product',
  tenant_id: 'tenant-demo',
  name: '产品部',
  code: 'PRODUCT',
  parent_id: null,
  manager_user_id: 'user-admin',
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const employee: EmployeeRead = {
  id: 'employee-admin',
  tenant_id: 'tenant-demo',
  user_id: 'user-admin',
  username: 'admin',
  display_name: '管理员',
  avatar_url: null,
  employee_no: 'E001',
  department_id: department.id,
  job_title: '项目负责人',
  business_role: 'admin',
  level: 'P8',
  skills: ['项目管理'],
  capacity_percent: 80,
  daily_cost: 1600,
  manager_user_id: null,
  assistant_agent_id: null,
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const project: ProjectRead = {
  id: 'project-launch',
  tenant_id: 'tenant-demo',
  name: '产品发布',
  objective: '按期完成新版发布',
  description: '跨部门发布项目',
  owner_user_id: 'user-admin',
  department_id: department.id,
  status: 'active',
  health: 'on_track',
  start_date: '2026-09-01',
  due_date: '2026-09-20',
  budget: 50000,
  version: 2,
  task_total: 4,
  task_done: 1,
  progress: 99,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

function renderProjects(user = admin) {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <ProjectsPage currentUser={user} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('ProjectsPage', () => {
  beforeEach(() => {
    vi.mocked(workbenchApi.listProjects).mockResolvedValue([project]);
    vi.mocked(workbenchApi.listDepartments).mockResolvedValue([department]);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([employee]);
    vi.mocked(workbenchApi.createProject).mockResolvedValue({
      ...project,
      id: 'project-growth',
      name: '增长计划',
      objective: '提升新客转化',
      task_total: 0,
      task_done: 0,
      progress: 0,
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('calculates card progress from task totals and links to filtered work', async () => {
    renderProjects();
    const card = await screen.findByRole('article', { name: '产品发布' });

    expect(within(card).getByText('25%')).toBeTruthy();
    expect(within(card).getByRole('link', { name: '查看任务' }).getAttribute('href'))
      .toBe('/enterprise/tasks?project_id=project-launch');
    expect(within(card).getByRole('link', { name: 'AI 规划' }).getAttribute('href'))
      .toBe('/enterprise/planning?project_id=project-launch');
  });

  it('lets an administrator create a real project', async () => {
    const user = userEvent.setup();
    renderProjects();
    await screen.findByText('产品发布');

    await user.click(screen.getByRole('button', { name: '新建项目' }));
    const dialog = await screen.findByRole('dialog', { name: '新建项目' });
    await user.type(within(dialog).getByLabelText('项目名称'), '增长计划');
    await user.type(within(dialog).getByLabelText('项目目标'), '提升新客转化');
    await user.selectOptions(within(dialog).getByLabelText('所属部门'), department.id);
    await user.click(within(dialog).getByRole('button', { name: '创建项目' }));

    expect(await screen.findByText('增长计划')).toBeTruthy();
    expect(workbenchApi.createProject).toHaveBeenCalledWith({
      tenant_id: 'tenant-demo',
      name: '增长计划',
      objective: '提升新客转化',
      description: null,
      owner_user_id: 'user-admin',
      department_id: department.id,
      start_date: null,
      due_date: null,
      budget: null,
    });
  });

  it('shows empty, retryable error, and permission-denied states without mutation controls', async () => {
    vi.mocked(workbenchApi.listProjects).mockResolvedValueOnce([]);
    const view = renderProjects();
    expect(await screen.findByText('还没有可见项目')).toBeTruthy();
    view.unmount();

    vi.mocked(workbenchApi.listProjects)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce([project]);
    const user = userEvent.setup();
    renderProjects();
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('项目加载失败'));
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('产品发布')).toBeTruthy();
    cleanup();

    vi.mocked(workbenchApi.listProjects).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Forbidden"}', 'Forbidden'),
    );
    renderProjects({ ...admin, role: 'member' });
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', expect.stringContaining('无权查看项目中心'));
    expect(screen.queryByRole('button', { name: '新建项目' })).toBeNull();
  });
});
