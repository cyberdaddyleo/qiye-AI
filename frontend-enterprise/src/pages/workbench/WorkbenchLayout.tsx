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
        onLogout={onLogout}
        userName={currentUser?.username}
        left={(
          <div className="flex min-w-0 flex-col gap-[6px]">
            <h1 className="m-0 text-[22px] font-semibold leading-tight text-[#18181a]">{title}</h1>
            {description && (
              <p className="m-0 text-[13px] leading-[20px] text-[#757f9c]">{description}</p>
            )}
          </div>
        )}
        right={actions}
      />
      {children && <div className="pt-[24px]">{children}</div>}
    </main>
  );
}
