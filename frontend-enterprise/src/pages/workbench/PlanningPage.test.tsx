// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { I18nProvider } from '@/i18n';
import type {
  EmployeeRead,
  PlanRead,
  PlanVariant,
  ProjectRead,
  TaskRead,
  WorkbenchAccessRead,
} from '@/types/workbench';

import PlanningPage from './PlanningPage';
import { workbenchApi } from './workbenchApi';

vi.mock('./workbenchApi', async (importOriginal) => {
  const original = await importOriginal<typeof import('./workbenchApi')>();
  return {
    ...original,
    workbenchApi: {
      ...original.workbenchApi,
      getAccess: vi.fn(),
      listProjects: vi.fn(),
      listEmployees: vi.fn(),
      previewPlan: vi.fn(),
      dispatchPlan: vi.fn(),
    },
  };
});

const manager: EnterpriseAuthUser = {
  id: 'user-manager',
  tenant_id: 'tenant-demo',
  username: 'manager',
  display_name: '周经理',
  role: 'member',
};

const managerAccess: WorkbenchAccessRead = {
  tenant_id: manager.tenant_id,
  user_id: manager.id,
  business_role: 'manager',
  directory_scope: 'department',
  can_create_project: true,
};

const project: ProjectRead = {
  id: 'project-launch',
  tenant_id: manager.tenant_id,
  name: '新品发布',
  objective: '在九月完成新品发布',
  description: '跨职能发布项目',
  owner_user_id: manager.id,
  department_id: 'department-product',
  status: 'active',
  health: 'on_track',
  start_date: '2026-09-05',
  due_date: '2026-09-30',
  budget: 50000,
  version: 1,
  task_total: 0,
  task_done: 0,
  progress: 0,
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

const employee: EmployeeRead = {
  id: 'employee-product',
  tenant_id: manager.tenant_id,
  user_id: 'user-product',
  username: 'linshan',
  display_name: '林珊',
  avatar_url: null,
  employee_no: 'E002',
  department_id: 'department-product',
  job_title: '产品经理',
  business_role: 'member',
  level: 'P6',
  skills: ['用户研究', '项目管理'],
  capacity_percent: 80,
  daily_cost: 1200,
  manager_user_id: manager.id,
  assistant_agent_id: 'agent-helper',
  status: 'active',
  created_at: '2026-09-01T08:00:00Z',
  updated_at: '2026-09-04T08:00:00Z',
};

function variant(
  key: PlanVariant['key'],
  name: string,
  strategy: PlanVariant['strategy'],
  cost: number,
  finishDate: string,
): PlanVariant {
  return {
    key,
    name,
    strategy,
    tasks: [
      {
        key: 'research',
        title: '用户研究',
        description: '验证核心场景',
        required_role: '产品经理',
        skills: ['用户研究'],
        estimate_days: key === 'B' ? 1 : 2,
        priority: 'high',
        depends_on: [],
        acceptance_criteria: '形成十份访谈结论',
        assignee_user_id: employee.user_id,
        start_date: '2026-09-06',
        due_date: key === 'B' ? '2026-09-06' : '2026-09-07',
        assignment: {
          total_score: 0.92,
          effective_capacity_percent: 80,
          rationale: '岗位与用户研究技能匹配，且当前仍有可用容量。',
        },
        unassigned_reason: null,
      },
      {
        key: 'launch',
        title: '上线发布',
        description: '完成发布与公告',
        required_role: '发布负责人',
        skills: ['发布管理'],
        estimate_days: 1,
        priority: 'urgent',
        depends_on: ['research'],
        acceptance_criteria: '发布清单全部勾选',
        assignee_user_id: null,
        start_date: key === 'B' ? '2026-09-07' : '2026-09-08',
        due_date: key === 'B' ? '2026-09-07' : '2026-09-08',
        assignment: {},
        unassigned_reason: '没有同时满足发布经验与可用容量的员工',
      },
    ],
    metrics: {
      start_date: '2026-09-06',
      finish_date: finishDate,
      duration_workdays: key === 'B' ? 2 : 3,
      cost,
      critical_path: ['research', 'launch'],
      peak_parallelism: key === 'B' ? 2 : 1,
      effective_capacity_percent: { [employee.user_id]: key === 'B' ? 96 : 80 },
    },
    risks: key === 'B' ? ['快速方案的峰值负载较高'] : ['发布负责人仍待人工指派'],
    utilization: {
      [employee.user_id]: {
        assigned_days: key === 'B' ? 1 : 2,
        capacity_percent: 80,
        utilization_percent: key === 'B' ? 96 : 75,
      },
    },
  };
}

const fallbackPlan: PlanRead = {
  id: 'plan-launch',
  tenant_id: manager.tenant_id,
  project_id: project.id,
  created_by_user_id: manager.id,
  goal: '让新品在月底前成功上线',
  deadline: '2026-09-30',
  budget: 30000,
  constraints: { notes: '优先复用现有团队' },
  status: 'draft',
  source: 'fallback',
  variants: [
    variant('A', '均衡方案', 'balanced', 12000, '2026-09-08'),
    variant('B', '快速方案', 'fast', 15600, '2026-09-07'),
    variant('C', '成本方案', 'cost', 8800, '2026-09-10'),
  ],
  selected_variant: null,
  dispatch_idempotency_key: null,
  created_at: '2026-09-05T08:00:00Z',
  updated_at: '2026-09-05T08:00:00Z',
  dispatched_at: null,
};

const dispatchedTask: TaskRead = {
  id: 'task-research',
  tenant_id: manager.tenant_id,
  project_id: project.id,
  plan_id: fallbackPlan.id,
  parent_task_id: null,
  title: '用户研究',
  description: '验证核心场景',
  required_role: '产品经理',
  priority: 'high',
  status: 'backlog',
  assignee_user_id: employee.user_id,
  reviewer_user_id: manager.id,
  start_date: '2026-09-06',
  due_date: '2026-09-07',
  estimate_days: 2,
  progress: 0,
  acceptance_criteria: '形成十份访谈结论',
  result_summary: null,
  version: 0,
  dependencies: [],
  events: [],
  created_at: '2026-09-05T08:05:00Z',
  updated_at: '2026-09-05T08:05:00Z',
  completed_at: null,
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function renderPlanning(path = '/enterprise/planning?project_id=project-launch') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/enterprise/planning" element={<PlanningPage currentUser={manager} />} />
          <Route path="/enterprise/tasks" element={<p>已进入创建任务列表</p>} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

async function generatePlan(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole('heading', { name: '规划目标与约束' });
  await user.type(screen.getByLabelText('目标描述'), '让新品在月底前成功上线');
  await user.type(screen.getByLabelText('截止日期'), '2026-09-30');
  await user.type(screen.getByLabelText('预算'), '30000');
  await user.type(screen.getByLabelText('补充约束'), '优先复用现有团队');
  await user.click(screen.getByRole('button', { name: '生成三套方案' }));
}

async function enterConfirmation(user: ReturnType<typeof userEvent.setup>) {
  await generatePlan(user);
  await screen.findByText('内置规划引擎');
  await user.click(screen.getByRole('button', { name: '进入确认' }));
  await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
}

describe('PlanningPage', () => {
  beforeEach(() => {
    vi.mocked(workbenchApi.getAccess).mockResolvedValue(managerAccess);
    vi.mocked(workbenchApi.listProjects).mockResolvedValue([project]);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValue([employee]);
    vi.mocked(workbenchApi.previewPlan).mockResolvedValue(fallbackPlan);
    vi.mocked(workbenchApi.dispatchPlan).mockResolvedValue([dispatchedTask]);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('shows loading, useful empty, retryable error, and server-derived 403 states', async () => {
    const pendingProjects = deferred<ProjectRead[]>();
    vi.mocked(workbenchApi.listProjects).mockReturnValueOnce(pendingProjects.promise);
    renderPlanning();
    expect(screen.getByRole('status', { name: '规划上下文加载中' })).toBeTruthy();
    pendingProjects.resolve([]);
    expect(await screen.findByRole('heading', { name: '还没有可规划项目' })).toBeTruthy();
    cleanup();

    vi.mocked(workbenchApi.listProjects).mockRejectedValueOnce(new Error('offline'));
    renderPlanning();
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('规划上下文加载失败'),
    );
    cleanup();

    vi.mocked(workbenchApi.getAccess).mockResolvedValueOnce({
      ...managerAccess,
      business_role: 'member',
      directory_scope: 'self',
      can_create_project: false,
    });
    vi.mocked(workbenchApi.listEmployees).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Forbidden"}', 'Forbidden'),
    );
    renderPlanning();
    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('无权使用 AI 调度中心'),
    );
  });

  it('surfaces server validation errors without advancing the wizard', async () => {
    vi.mocked(workbenchApi.previewPlan).mockRejectedValueOnce(
      new ApiError(422, '{"detail":"deadline must be in the future"}', 'Unprocessable Entity'),
    );
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('规划参数未通过服务端校验'),
    );
    expect(screen.getByRole('heading', { name: '规划目标与约束' })).toBeTruthy();
  });

  it('renders editable fallback WBS, comparable metrics, rationale, and unassigned warnings', async () => {
    const preview = deferred<PlanRead>();
    vi.mocked(workbenchApi.previewPlan).mockReturnValueOnce(preview.promise);
    const user = userEvent.setup();
    renderPlanning();

    const generation = generatePlan(user);
    await waitFor(() => {
      expect(screen.getByRole('status', { name: '正在生成规划方案' })).toBeTruthy();
    });
    preview.resolve(fallbackPlan);
    await generation;

    expect(await screen.findByText('内置规划引擎')).toBeTruthy();
    expect(workbenchApi.previewPlan).toHaveBeenCalledWith({
      tenant_id: manager.tenant_id,
      project_id: project.id,
      goal: '让新品在月底前成功上线',
      deadline: '2026-09-30',
      budget: 30000,
      constraints: { notes: '优先复用现有团队' },
    });

    const balanced = screen.getByRole('article', { name: 'A 方案' });
    const fast = screen.getByRole('article', { name: 'B 方案' });
    const economical = screen.getByRole('article', { name: 'C 方案' });
    expect(balanced.textContent).toContain('¥12,000');
    expect(balanced.textContent).toContain('2026-09-08');
    expect(balanced.textContent).toContain('用户研究 → 上线发布');
    expect(fast.textContent).toContain('96%');
    expect(fast.textContent).toContain('快速方案的峰值负载较高');
    expect(economical.textContent).toContain('¥8,800');

    const wbs = screen.getByRole('region', { name: '可编辑 WBS' });
    expect(within(wbs).getByText('岗位与用户研究技能匹配，且当前仍有可用容量。')).toBeTruthy();
    expect(within(wbs).getByText('没有同时满足发布经验与可用容量的员工')).toBeTruthy();
    expect(within(wbs).getByText('1 项任务待人工指派')).toBeTruthy();

    await user.selectOptions(within(wbs).getByLabelText('上线发布负责人'), employee.user_id);
    expect(within(wbs).getByLabelText('上线发布负责人')).toHaveProperty('value', employee.user_id);
    await user.clear(within(wbs).getByLabelText('上线发布验收标准'));
    await user.type(within(wbs).getByLabelText('上线发布验收标准'), '灰度发布验证通过');
    expect(within(wbs).getByDisplayValue('灰度发布验证通过')).toBeTruthy();
    const dependency = within(wbs).getByRole('checkbox', { name: '上线发布依赖用户研究' });
    expect(dependency).toHaveProperty('checked', true);
    await user.click(dependency);
    expect(dependency).toHaveProperty('checked', false);

    await user.click(within(fast).getByRole('button', { name: '选择 B 方案' }));
    expect(within(fast).getByRole('button', { name: '选择 B 方案' }).getAttribute('aria-pressed')).toBe('true');
    expect(within(wbs).getByLabelText('上线发布截止日期')).toHaveProperty('value', '2026-09-07');
  });

  it('requires explicit confirmation, dispatches once with a stable key, and navigates to tasks', async () => {
    const dispatch = deferred<TaskRead[]>();
    vi.mocked(workbenchApi.dispatchPlan).mockReturnValueOnce(dispatch.promise);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    await screen.findByText('内置规划引擎');
    await user.click(screen.getByRole('button', { name: '选择 B 方案' }));
    await user.click(screen.getByRole('button', { name: '进入确认' }));

    expect(screen.getByRole('heading', { name: '确认下发方案' })).toBeTruthy();
    expect(screen.getByText('快速方案')).toBeTruthy();
    expect(screen.getByText('真人负责人 1 人 · 待人工指派 1 项')).toBeTruthy();
    expect(workbenchApi.dispatchPlan).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '确认并下发' })).toHaveProperty('disabled', true);

    await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
    await user.click(screen.getByRole('button', { name: '确认并下发' }));
    expect(screen.getByRole('button', { name: '下发中…' })).toHaveProperty('disabled', true);
    expect(workbenchApi.dispatchPlan).toHaveBeenCalledTimes(1);
    const firstRequest = vi.mocked(workbenchApi.dispatchPlan).mock.calls[0][1];
    expect(firstRequest.tenant_id).toBe(manager.tenant_id);
    expect(firstRequest.variant_key).toBe('B');
    expect(firstRequest.idempotency_key.length).toBeGreaterThan(8);

    dispatch.resolve([dispatchedTask]);
    expect(await screen.findByText('已进入创建任务列表')).toBeTruthy();
  });

  it('reuses a key while retrying one dispatch intent and renews it after returning to edit', async () => {
    vi.mocked(workbenchApi.dispatchPlan)
      .mockRejectedValueOnce(new Error('connection reset'))
      .mockRejectedValueOnce(new Error('connection reset again'))
      .mockResolvedValueOnce([dispatchedTask]);
    const user = userEvent.setup();
    renderPlanning();

    await enterConfirmation(user);
    await user.click(screen.getByRole('button', { name: '确认并下发' }));
    expect(await screen.findByText('下发失败，请确认网络后重试。')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '重试下发' }));
    expect(await screen.findByText('下发失败，请确认网络后重试。')).toBeTruthy();

    const firstKey = vi.mocked(workbenchApi.dispatchPlan).mock.calls[0][1].idempotency_key;
    const retryKey = vi.mocked(workbenchApi.dispatchPlan).mock.calls[1][1].idempotency_key;
    expect(retryKey).toBe(firstKey);

    await user.click(screen.getByRole('button', { name: '返回调整' }));
    await user.click(screen.getByRole('button', { name: '进入确认' }));
    await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
    await user.click(screen.getByRole('button', { name: '确认并下发' }));
    await screen.findByText('已进入创建任务列表');

    const newIntentKey = vi.mocked(workbenchApi.dispatchPlan).mock.calls[2][1].idempotency_key;
    expect(newIntentKey).not.toBe(firstKey);
  });

  it('shows a plan conflict without claiming tasks were created', async () => {
    vi.mocked(workbenchApi.dispatchPlan).mockRejectedValueOnce(
      new ApiError(409, '{"detail":"Plan was already dispatched"}', 'Conflict'),
    );
    const user = userEvent.setup();
    renderPlanning();

    await enterConfirmation(user);
    await user.click(screen.getByRole('button', { name: '确认并下发' }));

    expect(await screen.findByRole('alert')).toHaveProperty(
      'textContent',
      expect.stringContaining('方案状态已变化'),
    );
    expect(screen.queryByText('已进入创建任务列表')).toBeNull();
  });
});
