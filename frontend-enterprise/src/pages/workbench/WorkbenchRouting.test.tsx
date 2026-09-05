// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '@/i18n';
import type { TaskUpdateRequest } from '@/types/workbench';

import App from '../../App';
import { EnterpriseRoute } from '../../enums/routes';
import {
  commentTask,
  createDepartment,
  createProject,
  dispatchPlan,
  getAccess,
  getDashboard,
  getTask,
  importEmployees,
  listDepartments,
  listEmployees,
  listProjects,
  listTasks,
  previewPlan,
  reviewTask,
  submitTask,
  updateEmployee,
  updateTask,
} from './workbenchApi';

vi.mock('../dashboard/DashboardPage', () => ({
  default: () => <div data-testid="legacy-dashboard" />,
}));
vi.mock('../AgentsPage', () => ({ default: () => <div data-testid="legacy-agents" /> }));
vi.mock('../ChannelsPage', () => ({ default: () => <div data-testid="legacy-channels" /> }));
vi.mock('../KnowledgePage', () => ({
  default: () => <div data-testid="legacy-knowledge" />,
  KnowledgeAddPage: () => <div />,
}));
vi.mock('../GeneralSkillsPage', () => ({
  default: () => <div data-testid="legacy-skills" />,
  GeneralSkillEditPage: () => <div />,
  GeneralSkillNewPage: () => <div />,
}));
vi.mock('../SkillsPage', () => ({ default: () => <div data-testid="legacy-sop" /> }));
vi.mock('../ToolsPage', () => ({
  default: () => <div data-testid="legacy-tools" />,
  McpServerEditPage: () => <div />,
  McpServerNewPage: () => <div />,
  ToolEditPage: () => <div />,
  ToolNewPage: () => <div />,
  ToolTestPage: () => <div />,
}));
vi.mock('../AccountsPage', () => ({ default: () => <div data-testid="legacy-accounts" /> }));
vi.mock('../ModelsPage', () => ({ default: () => <div data-testid="legacy-models" /> }));
vi.mock('../RuntimeSettingsPage', () => ({
  default: () => <div data-testid="legacy-runtime-settings" />,
}));
vi.mock('../DistillPage', () => ({ default: () => null }));
vi.mock('../../components/OnboardingGuide', () => ({
  default: () => null,
  ONBOARDING_SEEN_KEY: 'staffdeck_onboarding_guide_seen',
}));
vi.mock('../../components/QuickStartGuide', () => ({
  default: () => null,
  QUICK_START_COMPLETED_EVENT: 'staffdeck-quick-start-completed',
  QUICK_START_SEEN_KEY: 'staffdeck_quick_start_guide_seen',
}));
vi.mock('../../components/UpdateReminder', () => ({ default: () => null }));

const authUser = {
  id: 'user-1',
  tenant_id: 'tenant_demo',
  username: 'admin',
  role: 'admin',
};

const agent = {
  id: 'agent-1',
  tenant_id: 'tenant_demo',
  name: '小艾',
  is_overall: false,
  status: 'active',
  metadata: {},
  resources: [],
  created_at: '2026-09-04T00:00:00Z',
  updated_at: '2026-09-04T00:00:00Z',
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? 'OK' : 'Bad Request',
    text: async () => JSON.stringify(body),
  } as Response;
}

function stubShellFetch() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/auth/me')) return jsonResponse(authUser);
    if (url.includes('/api/enterprise/workbench/access')) {
      return jsonResponse({
        tenant_id: authUser.tenant_id,
        user_id: authUser.id,
        business_role: 'admin',
        directory_scope: 'all',
        can_create_project: true,
        can_view_all: true,
        managed_department_ids: [],
      });
    }
    if (url.includes('/api/enterprise/workbench/dashboard')) {
      return jsonResponse({
        tenant_id: authUser.tenant_id,
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
    }
    if (url.includes('/api/enterprise/workbench/')) return jsonResponse([]);
    if (url.includes('/api/enterprise/agents')) return jsonResponse([agent]);
    if (url.includes('/api/enterprise/teams')) return jsonResponse([]);
    if (url.includes('/api/enterprise/model-configs')) return jsonResponse([{ id: 'model-1' }]);
    return jsonResponse([]);
  }));
}

function stubBrowserApis() {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
}

function renderAppAt(path: string) {
  window.history.pushState({}, '', path);
  return render(<I18nProvider><App /></I18nProvider>);
}

beforeEach(() => {
  stubBrowserApis();
  window.localStorage.setItem('ultrarag_auth', JSON.stringify({ token: 'token-1', user: authUser }));
  window.localStorage.setItem('staffdeck_onboarding_guide_seen', '1');
  window.localStorage.setItem('staffdeck_quick_start_guide_seen', '1');
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
  window.history.pushState({}, '', '/');
});

describe('enterprise workbench routing', () => {
  it('redirects the enterprise root and navigates all six workbench pages', async () => {
    stubShellFetch();
    const user = userEvent.setup();
    renderAppAt('/enterprise');

    await screen.findByRole('heading', { level: 1, name: '企业工作台' });
    expect(window.location.pathname).toBe(EnterpriseRoute.Workbench);

    const destinations = [
      [EnterpriseRoute.Workbench, '企业工作台', null],
      [EnterpriseRoute.Projects, '项目中心', '还没有可见项目'],
      [EnterpriseRoute.Planning, 'AI 调度中心', '还没有可规划项目'],
      [EnterpriseRoute.Tasks, '任务中心', '当前筛选下没有任务'],
      [EnterpriseRoute.MyWork, '员工工作台', '今天没有待处理工作'],
      [EnterpriseRoute.Organization, '组织与权限', null],
    ] as const;

    for (const [route, label, pageContent] of destinations) {
      const link = screen.getByRole('button', { name: label });
      await user.click(link);
      await screen.findByRole('heading', { level: 1, name: label });
      if (pageContent) await screen.findByRole('heading', { name: pageContent });
      expect(window.location.pathname).toBe(route);
      expect(link.getAttribute('data-active')).toBe('true');
    }
  });

  it('keeps a nested workbench path associated with its section', async () => {
    stubShellFetch();
    renderAppAt('/enterprise/tasks/task-123');

    await screen.findByRole('heading', { level: 1, name: '任务中心' });
    expect(window.location.pathname).toBe('/enterprise/tasks/task-123');
    expect(screen.getByRole('button', { name: '任务中心' }).getAttribute('data-active')).toBe('true');
  });

  it.each([
    ['/enterprise/dashboard', 'legacy-dashboard'],
    ['/enterprise/agents', 'legacy-agents'],
    ['/enterprise/knowledge', 'legacy-knowledge'],
    ['/enterprise/general-skills', 'legacy-skills'],
    ['/enterprise/skills', 'legacy-sop'],
    ['/enterprise/tools', 'legacy-tools'],
    ['/enterprise/channels', 'legacy-channels'],
    ['/enterprise/accounts', 'legacy-accounts'],
    ['/enterprise/models', 'legacy-models'],
    ['/enterprise/runtime-settings', 'legacy-runtime-settings'],
  ])('still resolves the legacy route %s', async (path, marker) => {
    stubShellFetch();
    renderAppAt(path);

    expect(await screen.findByTestId(marker)).toBeTruthy();
    expect(window.location.pathname).toBe(path);
  });
});

describe('typed workbench API boundary', () => {
  it('keeps submit-only result fields out of generic task updates', () => {
    const invalidUpdate: TaskUpdateRequest = {
      tenant_id: 'tenant_a',
      version: 1,
      // @ts-expect-error result_summary belongs to submitTask, not updateTask.
      result_summary: 'Delivered',
    };

    expect(invalidUpdate.tenant_id).toBe('tenant_a');
  });

  it('targets the existing JSON endpoints with exact methods and field names', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => (
      jsonResponse({})
    ));
    vi.stubGlobal('fetch', fetchMock);

    await getAccess('tenant_a');
    await getDashboard('tenant_a');
    await listProjects('tenant_a');
    await createProject({
      tenant_id: 'tenant_a',
      name: 'Launch',
      objective: 'Ship',
      department_id: 'dept-1',
    });
    await previewPlan({ tenant_id: 'tenant_a', project_id: 'project-1' });
    await dispatchPlan('plan-1', {
      tenant_id: 'tenant_a',
      variant_key: 'B',
      idempotency_key: 'dispatch-1',
      tasks: [
        {
          key: 'release',
          assignee_user_id: 'user-1',
          start_date: '2026-09-07',
          due_date: '2026-09-08',
          acceptance_criteria: 'Release accepted',
          depends_on: [],
        },
      ],
    });
    await listTasks({
      tenant_id: 'tenant_a',
      scope: 'all',
      status: 'review',
      project_id: 'project-1',
    });
    await getTask('task-1', 'tenant_a');
    await updateTask('task-1', { tenant_id: 'tenant_a', version: 2, progress: 80 });
    await commentTask('task-1', { tenant_id: 'tenant_a', version: 3, comment: 'Ready' });
    await submitTask('task-1', {
      tenant_id: 'tenant_a',
      version: 4,
      result_summary: 'Delivered',
      artifact_refs: ['asset-1'],
    });
    await reviewTask('task-1', {
      tenant_id: 'tenant_a',
      version: 5,
      verdict: 'approve',
      comment: 'Accepted',
    });
    await listDepartments('tenant_a');
    await createDepartment({ tenant_id: 'tenant_a', name: '研发', code: 'DEV' });
    await listEmployees('tenant_a');
    await updateEmployee('employee-1', {
      tenant_id: 'tenant_a',
      job_title: 'Staff Engineer',
      skills: ['TypeScript'],
    });

    const requests = fetchMock.mock.calls.map(([input, init]) => ({
      url: String(input),
      method: init?.method || 'GET',
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    }));
    expect(requests).toEqual([
      { url: '/api/enterprise/workbench/access?tenant_id=tenant_a', method: 'GET', body: undefined },
      { url: '/api/enterprise/workbench/dashboard?tenant_id=tenant_a', method: 'GET', body: undefined },
      { url: '/api/enterprise/workbench/projects?tenant_id=tenant_a', method: 'GET', body: undefined },
      {
        url: '/api/enterprise/workbench/projects',
        method: 'POST',
        body: { tenant_id: 'tenant_a', name: 'Launch', objective: 'Ship', department_id: 'dept-1' },
      },
      {
        url: '/api/enterprise/workbench/plans/preview',
        method: 'POST',
        body: { tenant_id: 'tenant_a', project_id: 'project-1' },
      },
      {
        url: '/api/enterprise/workbench/plans/plan-1/dispatch',
        method: 'POST',
        body: {
          tenant_id: 'tenant_a',
          variant_key: 'B',
          idempotency_key: 'dispatch-1',
          tasks: [
            {
              key: 'release',
              assignee_user_id: 'user-1',
              start_date: '2026-09-07',
              due_date: '2026-09-08',
              acceptance_criteria: 'Release accepted',
              depends_on: [],
            },
          ],
        },
      },
      {
        url: '/api/enterprise/workbench/tasks?tenant_id=tenant_a&scope=all&status=review&project_id=project-1',
        method: 'GET',
        body: undefined,
      },
      { url: '/api/enterprise/workbench/tasks/task-1?tenant_id=tenant_a', method: 'GET', body: undefined },
      {
        url: '/api/enterprise/workbench/tasks/task-1',
        method: 'PUT',
        body: { tenant_id: 'tenant_a', version: 2, progress: 80 },
      },
      {
        url: '/api/enterprise/workbench/tasks/task-1/comments',
        method: 'POST',
        body: { tenant_id: 'tenant_a', version: 3, comment: 'Ready' },
      },
      {
        url: '/api/enterprise/workbench/tasks/task-1/submit',
        method: 'POST',
        body: {
          tenant_id: 'tenant_a',
          version: 4,
          result_summary: 'Delivered',
          artifact_refs: ['asset-1'],
        },
      },
      {
        url: '/api/enterprise/workbench/tasks/task-1/review',
        method: 'POST',
        body: {
          tenant_id: 'tenant_a',
          version: 5,
          verdict: 'approve',
          comment: 'Accepted',
        },
      },
      { url: '/api/enterprise/workbench/departments?tenant_id=tenant_a', method: 'GET', body: undefined },
      {
        url: '/api/enterprise/workbench/departments',
        method: 'POST',
        body: { tenant_id: 'tenant_a', name: '研发', code: 'DEV' },
      },
      { url: '/api/enterprise/workbench/employees?tenant_id=tenant_a', method: 'GET', body: undefined },
      {
        url: '/api/enterprise/workbench/employees/employee-1',
        method: 'PATCH',
        body: { tenant_id: 'tenant_a', job_title: 'Staff Engineer', skills: ['TypeScript'] },
      },
    ]);
  });

  it('uploads employee imports as authenticated multipart data without forcing a content type', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => (
      jsonResponse({ created: 0, updated: 0, errors: [], results: [] })
    ));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['username,department\nleo,研发'], 'employees.csv', { type: 'text/csv' });

    await importEmployees(file, 'tenant_a');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe('/api/enterprise/workbench/employees/import?tenant_id=tenant_a');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get('file')).toBe(file);
    expect(init?.headers).toEqual({ Authorization: 'Bearer token-1' });
  });
});
