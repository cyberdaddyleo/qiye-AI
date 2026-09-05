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
  can_view_all: false,
  managed_department_ids: ['department-product'],
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

const alternateEmployee: EmployeeRead = {
  ...employee,
  id: 'employee-delivery',
  user_id: 'user-delivery',
  username: 'chenyu',
  display_name: '陈宇',
  employee_no: 'E003',
  job_title: '交付经理',
  skills: ['发布管理'],
};

const secondAlternateEmployee: EmployeeRead = {
  ...alternateEmployee,
  id: 'employee-operations',
  user_id: 'user-operations',
  username: 'zhaoming',
  display_name: '赵明',
  employee_no: 'E004',
  job_title: '运营经理',
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
  selected_variant_snapshot: null,
  dispatch_overrides: [],
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

function renderPlanning(
  path = '/enterprise/planning?project_id=project-launch',
  currentUser = manager,
) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/enterprise/planning" element={<PlanningPage currentUser={currentUser} />} />
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
      can_view_all: false,
      managed_department_ids: [],
    });
    vi.mocked(workbenchApi.listProjects).mockResolvedValueOnce([
      { ...project, owner_user_id: 'user-other', department_id: 'department-other' },
    ]);
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

  it('replaces employee identifiers in historical planner risks before rendering them', async () => {
    const historicalPlan: PlanRead = {
      ...fallbackPlan,
      variants: fallbackPlan.variants.map((candidate) => ({
        ...candidate,
        risks: [
          `快速方案将员工 ${employee.user_id} 容量由 80%→96%，需关注过载`,
        ],
      })),
    };
    vi.mocked(workbenchApi.previewPlan).mockResolvedValueOnce(historicalPlan);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    const fast = await screen.findByRole('article', { name: 'B 方案' });

    expect(fast.textContent).toContain('快速方案将员工 林珊 容量由 80%→96%');
    expect(document.body.textContent).not.toContain(employee.user_id);
  });

  it('replaces only complete employee identifiers in risks and rationales', async () => {
    const prefixEmployee: EmployeeRead = {
      ...employee,
      id: 'employee-prefix',
      user_id: 'user-a',
      username: 'prefix',
      display_name: '短前缀员工',
      employee_no: 'E101',
    };
    const overlappingEmployee: EmployeeRead = {
      ...employee,
      id: 'employee-overlapping',
      user_id: 'user-admin',
      username: 'overlapping',
      display_name: '长前缀员工',
      employee_no: 'E102',
    };
    const shortIdEmployee: EmployeeRead = {
      ...employee,
      id: 'employee-short-id',
      user_id: 'art',
      username: 'short-id',
      display_name: '短 ID 员工',
      employee_no: 'E103',
    };
    const boundaryPlan: PlanRead = {
      ...fallbackPlan,
      variants: fallbackPlan.variants.map((candidate) => ({
        ...candidate,
        risks: [
          '边界：(user-admin)、[user-a]、art；user-administrator、xuser-a、cartography 保持原样。',
        ],
        tasks: candidate.tasks.map((task) => task.key === 'research' ? {
          ...task,
          assignee_user_id: prefixEmployee.user_id,
          assignment: {
            ...task.assignment,
            candidate_scores: {
              'user-a': { total_score: 92 },
              'user-admin': { total_score: 90 },
              art: { total_score: 88 },
            },
            rationale: '推荐 user-admin 与 art 支援 user-a；user-administrator、smart、xuser-a 保持原样。',
          },
        } : task),
      })),
    };
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([
      prefixEmployee,
      overlappingEmployee,
      shortIdEmployee,
    ]);
    vi.mocked(workbenchApi.previewPlan).mockResolvedValueOnce(boundaryPlan);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    const balanced = await screen.findByRole('article', { name: 'A 方案' });
    expect(balanced.textContent).toContain(
      '边界：(长前缀员工)、[短前缀员工]、短 ID 员工；user-administrator、xuser-a、cartography 保持原样。',
    );
    const wbs = screen.getByRole('region', { name: '可编辑 WBS' });
    expect(wbs.textContent).toContain(
      '推荐 长前缀员工 与 短 ID 员工 支援 短前缀员工；user-administrator、smart、xuser-a 保持原样。',
    );
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
    expect(firstRequest.tasks).toEqual(fallbackPlan.variants[1].tasks.map((task) => ({
      key: task.key,
      assignee_user_id: task.assignee_user_id,
      start_date: task.start_date,
      due_date: task.due_date,
      acceptance_criteria: task.acceptance_criteria,
      depends_on: task.depends_on,
    })));

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

  it('dispatches the edited WBS and labels manual assignment provenance and frozen estimates', async () => {
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([employee, alternateEmployee]);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    const wbs = await screen.findByRole('region', { name: '可编辑 WBS' });
    await user.selectOptions(
      within(wbs).getByLabelText('用户研究负责人'),
      alternateEmployee.user_id,
    );
    expect(within(wbs).getByText('人工改派')).toBeTruthy();
    expect(within(wbs).queryByText('岗位与用户研究技能匹配，且当前仍有可用容量。')).toBeNull();

    await user.selectOptions(within(wbs).getByLabelText('上线发布负责人'), employee.user_id);
    expect(within(wbs).getByText('人工指定')).toBeTruthy();
    expect(within(wbs).queryByText('依据岗位、技能、容量与协作连续性综合推荐。')).toBeNull();
    await user.clear(within(wbs).getByLabelText('上线发布截止日期'));
    await user.type(within(wbs).getByLabelText('上线发布截止日期'), '2026-09-09');
    await user.clear(within(wbs).getByLabelText('上线发布验收标准'));
    await user.type(within(wbs).getByLabelText('上线发布验收标准'), '人工验收后的发布清单');
    await user.click(within(wbs).getByRole('checkbox', { name: '上线发布依赖用户研究' }));

    expect(screen.getAllByText('AI 原始方案估算').length).toBeGreaterThan(0);
    expect(screen.getByText('WBS 已修改，估算未重新计算')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: '进入确认' }));
    expect(screen.getByText('已修改 WBS')).toBeTruthy();
    expect(screen.getByText(/以下为人工编辑后的 WBS/)).toBeTruthy();
    expect(screen.getByText('AI 原始预计完成')).toBeTruthy();
    expect(screen.getByText('AI 原始预计成本')).toBeTruthy();

    await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
    await user.click(screen.getByRole('button', { name: '确认并下发' }));
    await waitFor(() => expect(workbenchApi.dispatchPlan).toHaveBeenCalledTimes(1));
    const request = vi.mocked(workbenchApi.dispatchPlan).mock.calls[0][1];
    expect(request.tasks).toEqual(expect.arrayContaining([
      expect.objectContaining({ key: 'research', assignee_user_id: alternateEmployee.user_id }),
      expect.objectContaining({
        key: 'launch',
        assignee_user_id: employee.user_id,
        due_date: '2026-09-09',
        acceptance_criteria: '人工验收后的发布清单',
        depends_on: [],
      }),
    ]));
  });

  it('keeps originally unassigned tasks marked manually assigned across repeated choices', async () => {
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([
      employee,
      alternateEmployee,
      secondAlternateEmployee,
    ]);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    const wbs = await screen.findByRole('region', { name: '可编辑 WBS' });
    const assignee = within(wbs).getByLabelText('上线发布负责人');
    await user.selectOptions(assignee, alternateEmployee.user_id);
    expect(within(wbs).getByText('人工指定')).toBeTruthy();

    await user.selectOptions(assignee, secondAlternateEmployee.user_id);
    expect(within(wbs).getByText('人工指定')).toBeTruthy();
    expect(within(wbs).queryByText('人工改派')).toBeNull();
  });

  it('keeps AI-assigned tasks marked manually reassigned across repeated choices', async () => {
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([
      employee,
      alternateEmployee,
      secondAlternateEmployee,
    ]);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    const wbs = await screen.findByRole('region', { name: '可编辑 WBS' });
    const assignee = within(wbs).getByLabelText('用户研究负责人');
    await user.selectOptions(assignee, alternateEmployee.user_id);
    expect(within(wbs).getByText('人工改派')).toBeTruthy();

    await user.selectOptions(assignee, secondAlternateEmployee.user_id);
    expect(within(wbs).getByText('人工改派')).toBeTruthy();
    expect(within(wbs).queryByText('人工指定')).toBeNull();
  });

  it('restores the immutable AI assignment and rationale when reassignment is reverted', async () => {
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([employee, alternateEmployee]);
    const user = userEvent.setup();
    renderPlanning();

    await generatePlan(user);
    const wbs = await screen.findByRole('region', { name: '可编辑 WBS' });
    const assignee = within(wbs).getByLabelText('用户研究负责人');
    await user.selectOptions(assignee, alternateEmployee.user_id);
    expect(within(wbs).getByText('人工改派')).toBeTruthy();

    await user.selectOptions(assignee, employee.user_id);
    expect(within(wbs).queryByText('人工改派')).toBeNull();
    expect(within(wbs).getByText('岗位与用户研究技能匹配，且当前仍有可用容量。')).toBeTruthy();
    expect(screen.queryByText('WBS 已修改，估算未重新计算')).toBeNull();

    await user.click(screen.getByRole('button', { name: '进入确认' }));
    expect(screen.queryByText('已修改 WBS')).toBeNull();
    await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
    await user.click(screen.getByRole('button', { name: '确认并下发' }));
    await waitFor(() => expect(workbenchApi.dispatchPlan).toHaveBeenCalledTimes(1));
    expect(vi.mocked(workbenchApi.dispatchPlan).mock.calls[0][1].tasks).toEqual(
      fallbackPlan.variants[0].tasks.map((task) => ({
        key: task.key,
        assignee_user_id: task.assignee_user_id,
        start_date: task.start_date,
        due_date: task.due_date,
        acceptance_criteria: task.acceptance_criteria,
        depends_on: task.depends_on,
      })),
    );
  });

  it('truthfully carries restricted-directory assignments from owner preview to dispatch', async () => {
    const ownerAccess: WorkbenchAccessRead = {
      ...managerAccess,
      business_role: 'member',
      directory_scope: 'self',
      can_create_project: false,
      can_view_all: false,
      managed_department_ids: [],
    };
    const restrictedAssigneeIds = ['user-restricted-research', 'user-restricted-launch'];
    const restrictedPlan: PlanRead = {
      ...fallbackPlan,
      variants: fallbackPlan.variants.map((candidate) => ({
        ...candidate,
        risks: [
          `快速方案将员工 ${restrictedAssigneeIds[0]} 容量由 80%→96%，需关注过载`,
        ],
        utilization: {
          [restrictedAssigneeIds[0]]: {
            assigned_days: 2,
            capacity_percent: 80,
            utilization_percent: 75,
          },
          [restrictedAssigneeIds[1]]: {
            assigned_days: 1,
            capacity_percent: 70,
            utilization_percent: 60,
          },
        },
        tasks: candidate.tasks.map((task, index) => ({
          ...task,
          assignee_user_id: restrictedAssigneeIds[index],
          assignment: { rationale: '受限目录中的内部匹配依据' },
          unassigned_reason: null,
        })),
      })),
    };
    vi.mocked(workbenchApi.getAccess).mockResolvedValueOnce(ownerAccess);
    vi.mocked(workbenchApi.listEmployees).mockRejectedValueOnce(
      new ApiError(403, '{"detail":"Forbidden"}', 'Forbidden'),
    );
    vi.mocked(workbenchApi.previewPlan).mockResolvedValueOnce(restrictedPlan);
    const user = userEvent.setup();
    renderPlanning('/enterprise/planning?project_id=project-launch', manager);

    expect(await screen.findByRole('heading', { name: '规划目标与约束' })).toBeTruthy();
    await generatePlan(user);
    await screen.findByText('内置规划引擎');
    const wbs = screen.getByRole('region', { name: '可编辑 WBS' });
    expect(within(wbs).getAllByText('已指派（员工目录信息受限）')).toHaveLength(2);
    expect(within(wbs).getAllByRole('option', {
      name: 'AI 原负责人 · 目录信息受限',
    })).toHaveLength(2);
    expect(within(wbs).queryByText(/暂无合适员工/)).toBeNull();
    expect(document.body.textContent).toContain('快速方案将员工 真人员工 容量由 80%→96%');
    for (const userId of restrictedAssigneeIds) {
      expect(document.body.textContent).not.toContain(userId);
    }

    const researchAssignee = within(wbs).getByLabelText('用户研究负责人');
    await user.selectOptions(researchAssignee, '');
    expect(researchAssignee).toHaveProperty('value', '');
    expect(within(researchAssignee).getByRole('option', {
      name: 'AI 原负责人 · 目录信息受限',
    })).toBeTruthy();

    await user.selectOptions(researchAssignee, restrictedAssigneeIds[0]);
    expect(researchAssignee).toHaveProperty('value', restrictedAssigneeIds[0]);
    expect(within(wbs).queryByText('人工改派')).toBeNull();
    expect(within(wbs).queryByText('人工指定')).toBeNull();
    expect(within(wbs).getAllByText('受限目录中的内部匹配依据')).toHaveLength(2);
    expect(screen.queryByText('WBS 已修改，估算未重新计算')).toBeNull();

    await user.click(screen.getByRole('button', { name: '进入确认' }));
    expect(screen.getByText('真人负责人 2 人 · 待人工指派 0 项')).toBeTruthy();
    expect(screen.getAllByText('已指派（员工目录信息受限）')).toHaveLength(2);
    for (const userId of restrictedAssigneeIds) {
      expect(document.body.textContent).not.toContain(userId);
    }
    await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
    await user.click(screen.getByRole('button', { name: '确认并下发' }));

    await waitFor(() => expect(workbenchApi.dispatchPlan).toHaveBeenCalledTimes(1));
    expect(vi.mocked(workbenchApi.dispatchPlan).mock.calls[0][1].tasks.map(
      (task) => task.assignee_user_id,
    )).toEqual(restrictedAssigneeIds);
  });

  it('keeps a hidden AI original assignee available after choosing another visible employee', async () => {
    const ownerAccess: WorkbenchAccessRead = {
      ...managerAccess,
      business_role: 'member',
      directory_scope: 'self',
      can_create_project: false,
      can_view_all: false,
      managed_department_ids: [],
    };
    const originalAssigneeId = 'user-hidden-ai-owner';
    const restrictedPlan: PlanRead = {
      ...fallbackPlan,
      variants: fallbackPlan.variants.map((candidate) => ({
        ...candidate,
        tasks: candidate.tasks.map((task) => task.key === 'research' ? {
          ...task,
          assignee_user_id: originalAssigneeId,
          assignment: { rationale: '不可变 AI 原始匹配依据' },
        } : task),
      })),
    };
    vi.mocked(workbenchApi.getAccess).mockResolvedValueOnce(ownerAccess);
    vi.mocked(workbenchApi.listEmployees).mockResolvedValueOnce([alternateEmployee]);
    vi.mocked(workbenchApi.previewPlan).mockResolvedValueOnce(restrictedPlan);
    const user = userEvent.setup();
    renderPlanning('/enterprise/planning?project_id=project-launch', manager);

    await generatePlan(user);
    const wbs = await screen.findByRole('region', { name: '可编辑 WBS' });
    const assignee = within(wbs).getByLabelText('用户研究负责人');
    expect(within(assignee).getByRole('option', {
      name: 'AI 原负责人 · 目录信息受限',
    })).toBeTruthy();

    await user.selectOptions(assignee, alternateEmployee.user_id);
    expect(within(wbs).getByText('人工改派')).toBeTruthy();
    expect(within(assignee).getByRole('option', {
      name: 'AI 原负责人 · 目录信息受限',
    })).toBeTruthy();

    await user.selectOptions(assignee, originalAssigneeId);
    expect(within(wbs).queryByText('人工改派')).toBeNull();
    expect(within(wbs).getByText('不可变 AI 原始匹配依据')).toBeTruthy();
    expect(screen.queryByText('WBS 已修改，估算未重新计算')).toBeNull();

    await user.click(screen.getByRole('button', { name: '进入确认' }));
    await user.click(screen.getByRole('checkbox', { name: '我已确认由真人员工承担任务责任' }));
    await user.click(screen.getByRole('button', { name: '确认并下发' }));

    await waitFor(() => expect(workbenchApi.dispatchPlan).toHaveBeenCalledTimes(1));
    expect(vi.mocked(workbenchApi.dispatchPlan).mock.calls[0][1].tasks.find(
      (task) => task.key === 'research',
    )?.assignee_user_id).toBe(originalAssigneeId);
  });
});
