// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
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
      getAccess: vi.fn(),
      listDepartments: vi.fn(),
      createDepartment: vi.fn(),
      updateDepartment: vi.fn(),
      listEmployees: vi.fn(),
      listTenantUsers: vi.fn(),
      createEmployee: vi.fn(),
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

const inactiveEmployee: EmployeeRead = {
  ...employee,
  id: 'employee-former',
  user_id: 'user-former',
  username: 'former',
  display_name: '离职员工',
  employee_no: 'E003',
  status: 'inactive',
};

const newEmployee: EmployeeRead = {
  ...employee,
  id: 'employee-new',
  user_id: 'user-new',
  username: 'new.user',
  display_name: '新增成员',
  employee_no: 'E009',
  job_title: '增长运营',
  business_role: 'member',
  skills: ['增长', '数据分析'],
  capacity_percent: 75,
  daily_cost: 900,
  manager_user_id: null,
};

const tenantUsers = [
  {
    id: admin.id,
    tenant_id: admin.tenant_id,
    username: admin.username,
    display_name: admin.display_name,
    role: admin.role,
  },
  {
    id: employee.user_id,
    tenant_id: employee.tenant_id,
    username: employee.username,
    display_name: employee.display_name || undefined,
    role: 'member' as const,
  },
  {
    id: inactiveEmployee.user_id,
    tenant_id: inactiveEmployee.tenant_id,
    username: inactiveEmployee.username,
    display_name: inactiveEmployee.display_name || undefined,
    role: 'member' as const,
  },
  {
    id: newEmployee.user_id,
    tenant_id: newEmployee.tenant_id,
    username: newEmployee.username,
    display_name: newEmployee.display_name || undefined,
    role: 'member' as const,
  },
];

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
    vi.mocked(workbenchApi.getAccess).mockResolvedValue({
      tenant_id: admin.tenant_id,
      user_id: admin.id,
      business_role: 'admin',
      directory_scope: 'all',
      can_create_project: true,
      can_view_all: true,
      managed_department_ids: [],
    });
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
    vi.mocked(workbenchApi.updateDepartment).mockResolvedValue(department);
    vi.mocked(workbenchApi.listTenantUsers).mockResolvedValue(tenantUsers);
    vi.mocked(workbenchApi.createEmployee).mockResolvedValue(newEmployee);
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

  it('creates a complete employee profile from an unprofiled same-tenant account and refreshes organization data', async () => {
    vi.mocked(workbenchApi.listEmployees)
      .mockResolvedValueOnce([employee, inactiveEmployee])
      .mockResolvedValueOnce([employee, inactiveEmployee, newEmployee]);
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '手工建档' }));
    const dialog = await screen.findByRole('dialog', { name: '手工创建员工档案' });
    const account = within(dialog).getByLabelText('关联账号');
    expect(within(account).queryByRole('option', { name: /林珊/ })).toBeNull();
    expect(within(account).queryByRole('option', { name: /离职员工/ })).toBeNull();
    await user.selectOptions(account, newEmployee.user_id);
    await user.type(within(dialog).getByLabelText('员工工号'), 'E009');
    await user.type(within(dialog).getByLabelText('岗位'), '增长运营');
    await user.selectOptions(within(dialog).getByLabelText('所属部门'), department.id);
    await user.type(within(dialog).getByLabelText('职级'), 'P5');
    await user.type(within(dialog).getByLabelText('技能（逗号分隔）'), '增长，数据分析');
    await user.clear(within(dialog).getByLabelText('可用率'));
    await user.type(within(dialog).getByLabelText('可用率'), '75');
    await user.type(within(dialog).getByLabelText('日成本'), '900');
    await user.click(within(dialog).getByRole('button', { name: '创建员工档案' }));

    expect(workbenchApi.createEmployee).toHaveBeenCalledWith({
      tenant_id: admin.tenant_id,
      user_id: newEmployee.user_id,
      employee_no: 'E009',
      department_id: department.id,
      job_title: '增长运营',
      business_role: 'member',
      level: 'P5',
      skills: ['增长', '数据分析'],
      capacity_percent: 75,
      daily_cost: 900,
      manager_user_id: null,
      assistant_agent_id: null,
    });
    expect(await screen.findByText('新增成员')).toBeTruthy();
    expect(workbenchApi.listDepartments).toHaveBeenCalledTimes(2);
    expect(workbenchApi.listEmployees).toHaveBeenCalledTimes(2);
    expect(workbenchApi.getAccess).toHaveBeenCalledTimes(2);
  });

  it('shows an empty manual-profile state when every account already has an active or inactive profile', async () => {
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([employee, inactiveEmployee]);
    vi.mocked(workbenchApi.listTenantUsers).mockResolvedValue([
      tenantUsers[1],
      tenantUsers[2],
    ]);
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '手工建档' }));
    const dialog = await screen.findByRole('dialog', { name: '手工创建员工档案' });

    expect(within(dialog).getByText('所有同租户账号都已建立员工档案。')).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: '创建员工档案' })).toHaveProperty('disabled', true);
    expect(workbenchApi.createEmployee).not.toHaveBeenCalled();
  });

  it.each([
    [403, '当前账号无权创建员工档案。'],
    [409, '该账号已有员工档案，已刷新组织数据。'],
    [422, '员工档案信息不符合要求，请检查后重试。'],
  ])('handles employee creation HTTP %s without closing the form', async (status, message) => {
    vi.mocked(workbenchApi.createEmployee).mockRejectedValueOnce(
      new ApiError(status, JSON.stringify({ detail: 'request rejected' }), 'Request rejected'),
    );
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');
    await user.click(screen.getByRole('button', { name: '手工建档' }));
    const dialog = await screen.findByRole('dialog', { name: '手工创建员工档案' });
    await user.selectOptions(within(dialog).getByLabelText('关联账号'), newEmployee.user_id);
    await user.click(within(dialog).getByRole('button', { name: '创建员工档案' }));

    expect(await within(dialog).findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining(message),
    );
    expect(within(dialog).getByRole('button', { name: '创建员工档案' })).toBeTruthy();
  });

  it('appoints a real department manager and reloads departments, employees, and access', async () => {
    const appointedDepartment = { ...department, manager_user_id: employee.user_id };
    const existingManager = {
      ...employee,
      id: 'employee-existing-manager',
      user_id: 'user-existing-manager',
      username: 'existing.manager',
      display_name: '现任经理',
      business_role: 'manager' as const,
    };
    const ceoCandidate = {
      ...employee,
      id: 'employee-ceo-candidate',
      user_id: 'user-ceo-candidate',
      username: 'ceo.candidate',
      display_name: 'CEO 候选人',
      business_role: 'ceo' as const,
    };
    const legacyAdminCandidate = {
      ...employee,
      id: 'employee-legacy-admin',
      user_id: 'user-legacy-admin',
      username: 'legacy.admin',
      display_name: '历史管理员',
      business_role: 'admin' as const,
    };
    vi.mocked(workbenchApi.updateDepartment).mockResolvedValueOnce(appointedDepartment);
    vi.mocked(workbenchApi.listDepartments)
      .mockResolvedValueOnce([department])
      .mockResolvedValueOnce([appointedDepartment]);
    vi.mocked(workbenchApi.listEmployees)
      .mockResolvedValueOnce([employee, existingManager, ceoCandidate, legacyAdminCandidate, inactiveEmployee])
      .mockResolvedValueOnce([employee, existingManager, ceoCandidate, legacyAdminCandidate, inactiveEmployee]);
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '任命产品部负责人' }));
    const dialog = await screen.findByRole('dialog', { name: '任命部门负责人' });
    const managerSelect = within(dialog).getByLabelText('部门负责人');
    expect(within(managerSelect).getByRole('option', { name: /林珊/ })).toBeTruthy();
    expect(within(managerSelect).getByRole('option', { name: /现任经理/ })).toBeTruthy();
    expect(within(managerSelect).queryByRole('option', { name: /CEO 候选人/ })).toBeNull();
    expect(within(managerSelect).queryByRole('option', { name: /历史管理员/ })).toBeNull();
    expect(within(managerSelect).queryByRole('option', { name: /离职员工/ })).toBeNull();
    await user.selectOptions(managerSelect, employee.user_id);
    await user.click(within(dialog).getByRole('button', { name: '确认任命' }));

    expect(workbenchApi.updateEmployee).not.toHaveBeenCalled();
    expect(workbenchApi.updateDepartment).toHaveBeenCalledTimes(1);
    expect(workbenchApi.updateDepartment).toHaveBeenCalledWith(department.id, {
      tenant_id: admin.tenant_id,
      manager_user_id: employee.user_id,
    });
    await waitFor(() => {
      expect(workbenchApi.listDepartments).toHaveBeenCalledTimes(2);
      expect(workbenchApi.listEmployees).toHaveBeenCalledTimes(2);
      expect(workbenchApi.getAccess).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText('负责人：林珊')).toBeTruthy();
  });

  it('refreshes authoritative organization state after a rejected manager appointment', async () => {
    vi.mocked(workbenchApi.updateDepartment).mockRejectedValueOnce(
      new ApiError(422, JSON.stringify({ detail: 'manager must belong to department' }), 'Unprocessable Entity'),
    );
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '任命产品部负责人' }));
    const dialog = await screen.findByRole('dialog', { name: '任命部门负责人' });
    await user.selectOptions(within(dialog).getByLabelText('部门负责人'), employee.user_id);
    await user.click(within(dialog).getByRole('button', { name: '确认任命' }));

    expect(await within(dialog).findByRole('alert')).toHaveProperty(
      'textContent',
      '所选员工不符合部门负责人任命条件。',
    );
    expect(workbenchApi.updateDepartment).toHaveBeenCalledTimes(1);
    expect(workbenchApi.updateDepartment).toHaveBeenCalledWith(department.id, {
      tenant_id: admin.tenant_id,
      manager_user_id: employee.user_id,
    });
    expect(workbenchApi.updateEmployee).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(workbenchApi.listDepartments).toHaveBeenCalledTimes(2);
      expect(workbenchApi.listEmployees).toHaveBeenCalledTimes(2);
      expect(workbenchApi.getAccess).toHaveBeenCalledTimes(2);
    });
  });

  it('offers only member and global CEO choices in employee business-role selectors', async () => {
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('林珊');

    await user.click(screen.getByRole('button', { name: '编辑林珊' }));
    const editor = await screen.findByRole('dialog', { name: '编辑员工：林珊' });
    expect(Array.from(within(editor).getByLabelText<HTMLSelectElement>('业务角色').options).map((option) => option.value))
      .toEqual(['member', 'ceo']);
    await user.click(within(editor).getByRole('button', { name: '取消' }));

    await user.click(screen.getByRole('button', { name: '手工建档' }));
    const creator = await screen.findByRole('dialog', { name: '手工创建员工档案' });
    expect(Array.from(within(creator).getByLabelText<HTMLSelectElement>('业务角色').options).map((option) => option.value))
      .toEqual(['member', 'ceo']);
  });

  it('keeps an active department manager role read-only and omits it when saving other profile fields', async () => {
    const currentManager: EmployeeRead = {
      ...employee,
      id: 'employee-current-manager',
      user_id: 'user-current-manager',
      username: 'current.manager',
      display_name: '周经理',
      job_title: '产品负责人',
      business_role: 'manager',
      daily_cost: 1500,
      manager_user_id: null,
      assistant_agent_id: null,
    };
    const managedDepartment: DepartmentRead = {
      ...department,
      manager_user_id: currentManager.user_id,
    };
    vi.mocked(workbenchApi.listDepartments).mockResolvedValueOnce([managedDepartment]);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([currentManager]);
    vi.mocked(workbenchApi.updateEmployee).mockResolvedValueOnce({
      ...currentManager,
      job_title: '产品总监',
      daily_cost: 1800,
      assistant_agent_id: assistant.id,
    });
    const user = userEvent.setup();
    renderOrganization();
    await screen.findByText('周经理');

    await user.click(screen.getByRole('button', { name: '编辑周经理' }));
    const editor = await screen.findByRole('dialog', { name: '编辑员工：周经理' });
    const businessRole = within(editor).getByLabelText('业务角色');
    expect(businessRole).toHaveProperty('readOnly', true);
    expect(businessRole).toHaveProperty('value', '部门负责人');

    const title = within(editor).getByLabelText('岗位');
    await user.clear(title);
    await user.type(title, '产品总监');
    const dailyCost = within(editor).getByLabelText('日成本');
    await user.clear(dailyCost);
    await user.type(dailyCost, '1800');
    await user.selectOptions(within(editor).getByLabelText('AI 助理关联'), assistant.id);
    await user.click(within(editor).getByRole('button', { name: '保存员工档案' }));

    expect(await screen.findByText('产品总监')).toBeTruthy();
    expect(screen.getByText('AI 助理：产品研究助理')).toBeTruthy();
    expect(workbenchApi.updateEmployee).toHaveBeenCalledWith(currentManager.id, {
      tenant_id: admin.tenant_id,
      employee_no: currentManager.employee_no,
      department_id: managedDepartment.id,
      job_title: '产品总监',
      level: currentManager.level,
      skills: currentManager.skills,
      capacity_percent: currentManager.capacity_percent,
      daily_cost: 1800,
      manager_user_id: null,
      assistant_agent_id: assistant.id,
      status: 'active',
    });
    const updatePayload = vi.mocked(workbenchApi.updateEmployee).mock.calls[0]?.[1];
    expect(updatePayload).not.toHaveProperty('business_role');
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

  it('refreshes created and updated employees after a successful import report closes', async () => {
    const refreshedEmployee: EmployeeRead = {
      ...employee,
      job_title: '导入更新岗位',
    };
    const importedEmployee: EmployeeRead = {
      ...employee,
      id: 'employee-new',
      user_id: 'user-new',
      username: 'new.user',
      display_name: '新增员工',
      employee_no: 'E009',
      job_title: '运营专员',
    };
    vi.mocked(workbenchApi.listEmployees)
      .mockResolvedValueOnce([employee])
      .mockResolvedValueOnce([refreshedEmployee, importedEmployee]);
    const user = userEvent.setup();

    renderOrganization();
    await screen.findByText('林珊');
    await user.click(screen.getByRole('button', { name: '导入员工' }));
    const dialog = await screen.findByRole('dialog', { name: '导入员工' });
    await user.upload(
      within(dialog).getByLabelText('选择 CSV 或 XLSX 文件'),
      new File(['username,display_name\nnew.user,新增员工'], 'employees.csv', {
        type: 'text/csv',
      }),
    );
    await user.click(within(dialog).getByRole('button', { name: '开始导入' }));
    expect(await within(dialog).findByText('新增 1 人')).toBeTruthy();
    await user.click(within(dialog).getByRole('button', { name: '关闭' }));

    expect(await screen.findByText('新增员工')).toBeTruthy();
    expect(screen.getByText('导入更新岗位')).toBeTruthy();
    expect(workbenchApi.listEmployees).toHaveBeenCalledTimes(2);
  });

  it('shows a member returned organization data without mutation controls', async () => {
    vi.mocked(workbenchApi.getAccess).mockResolvedValueOnce({
      tenant_id: admin.tenant_id,
      user_id: employee.user_id,
      business_role: 'member',
      directory_scope: 'self',
      can_create_project: false,
      can_view_all: false,
      managed_department_ids: [],
    });
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
    expect(screen.queryByRole('button', { name: '手工建档' })).toBeNull();
    expect(screen.queryByRole('button', { name: '导入员工' })).toBeNull();
    expect(screen.queryByRole('button', { name: /编辑/ })).toBeNull();
  });

  it('uses server access for a non-global manager without exposing global organization actions', async () => {
    const managerUser: EnterpriseAuthUser = {
      id: 'user-manager',
      tenant_id: admin.tenant_id,
      username: 'manager',
      display_name: '部门经理',
      role: 'member',
    };
    vi.mocked(workbenchApi.getAccess).mockResolvedValueOnce({
      tenant_id: admin.tenant_id,
      user_id: managerUser.id,
      business_role: 'manager',
      directory_scope: 'department',
      can_create_project: true,
      can_view_all: false,
      managed_department_ids: [department.id],
    });
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([employee]);

    renderOrganization(managerUser);

    expect(await screen.findByRole('button', { name: '编辑林珊' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '手工建档' })).toBeNull();
    expect(screen.queryByRole('button', { name: '新建部门' })).toBeNull();
    expect(screen.queryByRole('button', { name: '导入员工' })).toBeNull();
    expect(screen.queryByLabelText('部门负责人管理')).toBeNull();
    expect(workbenchApi.listTenantUsers).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '编辑林珊' }));
    const editor = await screen.findByRole('dialog', { name: '编辑员工：林珊' });
    expect(Array.from(within(editor).getByLabelText<HTMLSelectElement>('业务角色').options).map((option) => option.value))
      .toEqual(['member']);
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
    expect(screen.queryByRole('button', { name: '手工建档' })).toBeNull();
    expect(screen.queryByRole('button', { name: '导入员工' })).toBeNull();
    expect(screen.queryByRole('button', { name: /编辑/ })).toBeNull();
    expect(workbenchApi.listTenantUsers).not.toHaveBeenCalled();
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
