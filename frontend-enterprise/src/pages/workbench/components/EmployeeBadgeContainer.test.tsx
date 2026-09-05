// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { EmployeeRead } from '@/types/workbench';

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

function storeSession() {
  window.localStorage.setItem('ultrarag_auth', JSON.stringify({
    token: 'session-secret',
    user: {
      id: employee.user_id,
      tenant_id: employee.tenant_id,
      username: employee.username,
      role: 'member',
    },
  }));
}

async function loadContainer() {
  return (await import('./EmployeeBadgeContainer')).default;
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('EmployeeBadgeContainer protected avatar loading', () => {
  it('deduplicates authenticated loads across simultaneous and later badges', async () => {
    vi.resetModules();
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test');
    storeSession();
    const blob = new Blob(['avatar'], { type: 'image/png' });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi.fn().mockResolvedValue(blob),
    });
    vi.stubGlobal('fetch', fetchMock);
    let objectUrlSequence = 0;
    vi.spyOn(URL, 'createObjectURL').mockImplementation(
      () => `blob:employee-avatar-${++objectUrlSequence}`,
    );
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const EmployeeBadgeContainer = await loadContainer();

    const firstView = render(
      <>
        <EmployeeBadgeContainer employee={employee} />
        <EmployeeBadgeContainer employee={employee} />
      </>,
    );

    await waitFor(() => expect(firstView.container.querySelectorAll('img')).toHaveLength(2));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `https://api.example.test${avatarPointer}`,
      { headers: { Authorization: 'Bearer session-secret' } },
    );
    expect(firstView.container.innerHTML).not.toContain('session-secret');
    expect(firstView.container.innerHTML).not.toContain(avatarPointer);

    firstView.unmount();
    const laterView = render(<EmployeeBadgeContainer employee={employee} />);
    await waitFor(() => expect(laterView.container.querySelector('img')).not.toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('revokes every subscriber object URL when badges unmount', async () => {
    vi.resetModules();
    storeSession();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi.fn().mockResolvedValue(new Blob(['avatar'], { type: 'image/png' })),
    });
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:employee-avatar');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const EmployeeBadgeContainer = await loadContainer();
    const view = render(<EmployeeBadgeContainer employee={employee} />);
    await waitFor(() => expect(view.container.querySelector('img')).not.toBeNull());

    view.unmount();

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:employee-avatar');
  });

  it('keeps initials when protected loading fails', async () => {
    vi.resetModules();
    storeSession();
    const fetchMock = vi.fn().mockRejectedValue(new Error('avatar unavailable'));
    vi.stubGlobal('fetch', fetchMock);
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:unexpected');
    const EmployeeBadgeContainer = await loadContainer();

    const view = render(<EmployeeBadgeContainer employee={employee} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText('林员工头像')).toHaveProperty('textContent', '林');
    expect(view.container.querySelector('img')).toBeNull();
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(view.container.innerHTML).not.toContain('session-secret');
    expect(view.container.innerHTML).not.toContain(avatarPointer);
  });
});
