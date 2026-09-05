// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { setEnterpriseAuthSession, type EnterpriseAuthUser } from '@/auth';
import { I18nProvider } from '@/i18n';

import WorkbenchLayout from './WorkbenchLayout';

const currentUser: EnterpriseAuthUser = {
  id: 'user-1',
  tenant_id: 'tenant_demo',
  username: 'admin',
  display_name: '管理员',
  role: 'admin',
};

describe('WorkbenchLayout', () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it('keeps page actions beside the default account and logout menu', async () => {
    setEnterpriseAuthSession({ token: 'session-token', user: currentUser });
    const user = userEvent.setup();
    const onLogout = vi.fn();

    render(
      <I18nProvider>
        <WorkbenchLayout
          title="项目中心"
          currentUser={currentUser}
          onLogout={onLogout}
          actions={<button type="button">新建项目</button>}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole('button', { name: '新建项目' })).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '账户菜单' }));
    await user.click(await screen.findByRole('menuitem', { name: '退出登录' }));
    expect(onLogout).toHaveBeenCalledOnce();
  });

  it('stacks the toolbar below an unbroken title on narrow screens', () => {
    render(
      <I18nProvider>
        <WorkbenchLayout
          title="组织架构"
          description="查看部门与员工，维护真人团队的职责、技能和工作容量"
          currentUser={currentUser}
          actions={<button type="button">导入员工</button>}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole('banner').classList.contains('max-[640px]:flex-col')).toBe(true);
    expect(
      screen.getByRole('heading', { name: '组织架构' }).classList.contains('whitespace-nowrap'),
    ).toBe(true);
  });
});
