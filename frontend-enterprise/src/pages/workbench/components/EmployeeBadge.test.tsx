// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { EmployeeRead } from '@/types/workbench';

import EmployeeBadge from './EmployeeBadge';

const avatarPointer = '/api/enterprise/workbench/employees/employee-lin/avatar?tenant_id=tenant-demo';

const employee: EmployeeRead = {
  id: 'employee-lin',
  tenant_id: 'tenant-demo',
  user_id: 'user-lin',
  username: 'lin',
  display_name: '林珊',
  avatar_url: avatarPointer,
  employee_no: 'E002',
  department_id: 'department-product',
  job_title: '产品经理',
  business_role: 'member',
  level: 'P6',
  skills: ['产品设计'],
  capacity_percent: 80,
  daily_cost: 1200,
  manager_user_id: null,
  assistant_agent_id: null,
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('EmployeeBadge display boundary', () => {
  it('uses only the caller-resolved avatar URL', () => {
    const fetchMock = vi.fn(() => new Promise(() => undefined));
    vi.stubGlobal('fetch', fetchMock);

    const view = render(
      <EmployeeBadge employee={employee} avatarUrl="blob:employee-avatar" />,
    );

    expect(view.container.querySelector('img')?.getAttribute('src')).toBe('blob:employee-avatar');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(view.container.innerHTML).not.toContain(avatarPointer);
  });

  it('renders initials when the caller supplies no resolved avatar', () => {
    const fetchMock = vi.fn(() => new Promise(() => undefined));
    vi.stubGlobal('fetch', fetchMock);

    const view = render(<EmployeeBadge employee={employee} avatarUrl={null} />);

    expect(screen.getByLabelText('林员工头像')).toHaveProperty('textContent', '林');
    expect(view.container.querySelector('img')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(view.container.innerHTML).not.toContain(avatarPointer);
  });
});
