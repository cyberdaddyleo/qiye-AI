// @vitest-environment jsdom

import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { I18nProvider } from '@/i18n';
import type { AgentProfileRead } from '@/types';
import type {
  DepartmentRead,
  EmployeeImportResult,
  EmployeeRead,
} from '@/types/workbench';

import OrganizationPage from './OrganizationPage';
import { workbenchApi } from './workbenchApi';

vi.mock('./workbenchApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('./workbenchApi')>();
  return {
    ...original,
    workbenchApi: {
      ...original.workbenchApi,
      listDepartments: vi.fn(),
      createDepartment: vi.fn(),
      listEmployees: vi.fn(),
      updateEmployee: vi.fn(),
      importEmployees: vi.fn(),
    },
  };
});

vi.mock('@/components/ui/app-toast', () => ({
  notify: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}));

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
  id: 'employee-lin',
  tenant_id: 'tenant-demo',
  user_id: 'user-lin',
  username: 'lin',
  display_name: '林珊',
  avatar_url: null,
  employee_no: 'E002',
  department_id: department.id,
  job_title: '产品经理',
  business_role: 'member',
  level: 'P6',
  skills: ['产品设计', '用户研究'],
  capacity_percent: 80,
  daily_cost: 1200,
  manager_user_id: 'user-admin',
  assistant_agent_id: null,
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const assistant: AgentProfileRead = {
  id: 'agent-product',
  tenant_id: 'tenant-demo',
  name: '产品研究助理',
  description: '辅助资料检索与分析',
  is_overall: false,
  status: 'active',
  metadata: {},
  resources: [],
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const importResult: EmployeeImportResult = {
  created: 1,
  updated: 1,
  errors: [
    { row: 4, code: 'invalid_business_role', message: 'business_role is invalid' },
  ],
  results: [
    { row: 2, username: 'new.user', status: 'created', password: 'temporary-pass' },
    { row: 3, username: 'lin', status: 'updated' },
  ],
};

function renderOrganization(user = admin) {
  return render(
    <I18nProvider>
      <MemoryRouter>
        <OrganizationPage currentUser={user} assistants={[assistant]} />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('OrganizationPage', () => {
  beforeEach(() => {
    vi.mocked(workbenchApi.listDepartments).mockResolvedValue([department]);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([employee]);
    vi.mocked(workbenchApi.createDepartment).mockResolvedValue({
      ...department,
      id: 'department-growth',
      name: '增长部',
      code: 'GROWTH',
    });
    vi.mocked(workbenchApi.updateEmployee).mockResolvedValue({
      ...employee,
      job_title: '高级产品经理',
      assistant_agent_id: assistant.id,
    });
    vi.mocked(workbenchApi.importEmployees).mockResolvedValue(importResult);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('lets an administrator create a department', async () => {
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '新建部门' }));
    const dialog = await screen.findByRole('dialog', { name: '新建部门' });
    await user.type(within(dialog).getByLabelText('部门名称'), '增长部');
    await user.type(within(dialog).getByLabelText('部门编码'), 'GROWTH');
    await user.click(within(dialog).getByRole('button', { name: '创建部门' }));

    expect(await screen.findByRole('button', { name: '增长部' })).toBeTruthy();
    expect(workbenchApi.createDepartment).toHaveBeenCalledWith({
      tenant_id: 'tenant-demo',
      name: '增长部',
      code: 'GROWTH',
    });
  });

  it('edits a real employee and binds an existing AI assistant as a capability', async () => {
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '编辑林珊' }));
    const sheet = await screen.findByRole('dialog', { name: '编辑员工：林珊' });
    const title = within(sheet).getByLabelText('岗位');
    await user.clear(title);
    await user.type(title, '高级产品经理');
    await user.selectOptions(within(sheet).getByLabelText('AI 助理关联'), assistant.id);
    await user.click(within(sheet).getByRole('button', { name: '保存员工档案' }));

    expect(await screen.findByText('高级产品经理')).toBeTruthy();
    expect(screen.getByText('AI 助理：产品研究助理')).toBeTruthy();
    expect(workbenchApi.updateEmployee).toHaveBeenCalledWith(
      employee.id,
      expect.objectContaining({
        tenant_id: 'tenant-demo',
        job_title: '高级产品经理',
        assistant_agent_id: assistant.id,
      }),
    );
  });

  it('accepts CSV/XLSX files and renders created, updated, and row-error results', async () => {
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '导入员工' }));
    const dialog = await screen.findByRole('dialog', { name: '导入员工' });
    const input = within(dialog).getByLabelText('选择 CSV 或 XLSX 文件') as HTMLInputElement;
    expect(input.accept).toBe('.csv,.xlsx');
    const file = new File(['username,display_name\nnew.user,新人'], 'employees.csv', {
      type: 'text/csv',
    });
    await user.upload(input, file);
    expect(within(dialog).getByText('employees.csv')).toBeTruthy();
    await user.click(within(dialog).getByRole('button', { name: '开始导入' }));

    expect(await screen.findByText('新增 1 人')).toBeTruthy();
    expect(screen.getByText('更新 1 人')).toBeTruthy();
    expect(screen.getByText('第 4 行')).toBeTruthy();
    expect(screen.getByText('invalid_business_role')).toBeTruthy();
    expect(screen.getByText('new.user')).toBeTruthy();
    expect(screen.getByText('已创建')).toBeTruthy();
    expect(screen.getByText('临时密码：temporary-pass')).toBeTruthy();
    expect(screen.getByText('lin')).toBeTruthy();
    expect(screen.getByText('已更新')).toBeTruthy();
    expect(workbenchApi.importEmployees).toHaveBeenCalledWith(file, 'tenant-demo');
  });

  it('shows a member returned organization data without mutation controls', async () => {
    renderOrganization({
      id: 'user-lin',
      tenant_id: 'tenant-demo',
      username: 'lin',
      display_name: '林珊',
      role: 'member',
    });

    expect(await screen.findByText('林珊')).toBeTruthy();
    expect(screen.getByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('组织信息为只读'),
    );
    expect(screen.queryByRole('button', { name: '新建部门' })).toBeNull();
    expect(screen.queryByRole('button', { name: '导入员工' })).toBeNull();
    expect(screen.queryByRole('button', { name: /编辑/ })).toBeNull();
  });

  it('shows a permission-denied state without organization mutations', async () => {
    vi.mocked(workbenchApi.listDepartments).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot view departments"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.listEmployees).mockRejectedValue(
      new ApiError(403, '{"detail":"Cannot list employees"}', 'Forbidden'),
    );

    renderOrganization({
      id: 'user-lin',
      tenant_id: 'tenant-demo',
      username: 'lin',
      display_name: '林珊',
      role: 'member',
    });

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('组织信息为只读'),
    );
    expect(screen.queryByRole('button', { name: '新建部门' })).toBeNull();
    expect(screen.queryByRole('button', { name: '导入员工' })).toBeNull();
    expect(screen.queryByRole('button', { name: /编辑/ })).toBeNull();
  });

  it('rejects unsupported import files before calling the backend', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderOrganization();
    await screen.findByText('林珊');
    await user.click(screen.getByRole('button', { name: '导入员工' }));
    const dialog = await screen.findByRole('dialog', { name: '导入员工' });
    const input = within(dialog).getByLabelText('选择 CSV 或 XLSX 文件');
    await user.upload(input, new File(['bad'], 'employees.txt', { type: 'text/plain' }));

    expect(within(dialog).getByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('仅支持 .csv 或 .xlsx 文件'),
    );
    expect(within(dialog).queryByRole('button', { name: '开始导入' })).toBeNull();
    expect(workbenchApi.importEmployees).not.toHaveBeenCalled();
  });
});
