import type { ReactNode } from 'react';

import type { EnterpriseAuthUser } from '@/auth';
import AppHeader from '@/components/AppHeader';

export type WorkbenchLayoutProps = {
  title: string;
  description?: string;
  currentUser?: EnterpriseAuthUser;
  onLogout?: () => void;
  actions?: ReactNode;
  children?: ReactNode;
};

export default function WorkbenchLayout({
  title,
  description,
  currentUser,
  onLogout,
  actions,
  children,
}: WorkbenchLayoutProps) {
  return (
    <main className="min-h-full w-full min-w-0 bg-[#f7f9fc] px-[48px] py-[32px] max-[900px]:px-[16px] max-[900px]:py-[20px]">
      <AppHeader
        className="max-[640px]:flex-col max-[640px]:gap-[12px] max-[640px]:[&>div:last-child]:h-auto max-[640px]:[&>div:last-child]:w-full max-[640px]:[&>div:last-child]:flex-wrap"
        onLogout={onLogout}
        userName={currentUser?.username}
        left={(
          <div className="flex min-w-0 flex-col gap-[6px]">
            <h1 className="m-0 whitespace-nowrap text-[22px] font-semibold leading-tight text-[#18181a]">{title}</h1>
            {description && (
              <p className="m-0 text-[13px] leading-[20px] text-[#757f9c]">{description}</p>
            )}
            {currentUser && (
              <p className="m-0 text-[11px] leading-[18px] text-[#757f9c]">
                <span>登录账号：</span><span>{currentUser.username}</span>
                {currentUser.role === 'admin' && <span className="ml-[8px] text-[#1a71ff]">系统管理员</span>}
              </p>
            )}
          </div>
        )}
        actions={actions}
      />
      {children && <div className="pt-[24px]">{children}</div>}
    </main>
  );
}
