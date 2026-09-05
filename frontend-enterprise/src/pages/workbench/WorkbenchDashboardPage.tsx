import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BriefcaseBusiness,
  CircleAlert,
  ClipboardCheck,
  Clock3,
  Coins,
  ListTodo,
  UsersRound,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTime } from '@/lib/enterprise-ui';
import type {
  DashboardRead,
  EmployeeRead,
  ProjectRead,
  TaskRead,
  WorkTaskEventRead,
  WorkloadRow,
} from '@/types/workbench';

import WorkbenchLayout from './WorkbenchLayout';
import { workbenchApi } from './workbenchApi';
import { formatWorkload, projectProgress, taskStatusLabel } from './workbenchModel';
import EmployeeBadgeContainer from './components/EmployeeBadgeContainer';
import WorkbenchKpi from './components/WorkbenchKpi';
import WorkloadBar from './components/WorkloadBar';

export type WorkbenchDashboardPageProps = {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
};

const EMPTY_DASHBOARD: DashboardRead = {
  tenant_id: '',
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
};

const PROJECT_HEALTH: Record<ProjectRead['health'], { label: string; className: string }> = {
  on_track: { label: '进展正常', className: 'bg-[#e9f7ef] text-[#018434]' },
  at_risk: { label: '存在风险', className: 'bg-[#fff4dd] text-[#a65f00]' },
  off_track: { label: '已经偏离', className: 'bg-[#fce7e7] text-[#d20b0b]' },
};

function normalizeDashboard(value: DashboardRead): DashboardRead {
  if (!value || Array.isArray(value) || typeof value !== 'object') return EMPTY_DASHBOARD;
  return {
    ...EMPTY_DASHBOARD,
    ...value,
    task_counts: value.task_counts || {},
    department_loads: Array.isArray(value.department_loads) ? value.department_loads : [],
    workload_rows: Array.isArray(value.workload_rows) ? value.workload_rows : [],
    pending_reviews: Array.isArray(value.pending_reviews) ? value.pending_reviews : [],
    at_risk_tasks: Array.isArray(value.at_risk_tasks) ? value.at_risk_tasks : [],
    project_summaries: Array.isArray(value.project_summaries) ? value.project_summaries : [],
    recent_events: Array.isArray(value.recent_events) ? value.recent_events : [],
  };
}

function formatCurrency(value: number): string {
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)}`;
}

function eventLabel(event: WorkTaskEventRead, employees: Map<string, EmployeeRead>): string {
  const actor = event.actor_user_id ? employees.get(event.actor_user_id) : undefined;
  const name = actor?.display_name || actor?.username || (event.actor_type === 'system' ? '系统' : '成员');
  const actions: Record<string, string> = {
    task_created: '创建了任务',
    task_updated: '更新了任务',
    task_commented: '评论了任务',
    task_submitted: '提交了任务',
    task_reviewed: '审核了任务',
    task_reworked: '退回了任务',
    task_completed: '完成了任务',
    plan_dispatched: '下发了执行方案',
  };
  return `${name}${actions[event.event_type] || '更新了工作动态'}`;
}

function DashboardLoading() {
  return (
    <div role="status" aria-label="工作台加载中" className="space-y-[20px]">
      <div className="grid grid-cols-1 gap-[14px] sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-[126px] rounded-[16px] bg-[#e9edf4]" />
        ))}
      </div>
      <div className="grid gap-[18px] xl:grid-cols-2">
        <Skeleton className="h-[260px] rounded-[16px] bg-[#e9edf4]" />
        <Skeleton className="h-[260px] rounded-[16px] bg-[#e9edf4]" />
      </div>
    </div>
  );
}

function DashboardError({
  permissionDenied,
  partial = false,
  onRetry,
}: {
  permissionDenied: boolean;
  partial?: boolean;
  onRetry: () => void;
}) {
  return (
    <section role="alert" className="rounded-[16px] border border-[#f1d4d4] bg-white px-[24px] py-[32px] text-center">
      <CircleAlert className="mx-auto size-[28px] text-[#d20b0b]" aria-hidden="true" />
      <h2 className="mt-[12px] text-[16px] font-semibold text-[#24262d]">
        {partial ? '工作台部分数据加载失败' : permissionDenied ? '无权查看工作台' : '工作台加载失败'}
      </h2>
      <p className="mt-[6px] text-[12px] leading-[20px] text-[#757f9c]">
        {partial
          ? '员工身份与成本数据不可用，为避免展示错误范围或金额，请重试。'
          : permissionDenied
            ? '当前账号没有此工作台的访问权限。'
            : '未能读取最新运营数据，请稍后重试。'}
      </p>
      <Button type="button" onClick={onRetry} className="mt-[16px] h-[34px] rounded-[10px] bg-[#18181a] px-[18px] text-[12px] text-white hover:bg-[#303030]">
        重试
      </Button>
    </section>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[16px] border border-[#edf0f5] bg-white p-[20px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
      <h3 className="m-0 text-[14px] font-semibold text-[#24262d]">{title}</h3>
      <div className="mt-[16px]">{children}</div>
    </section>
  );
}

function EmptyLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 flex min-h-[88px] items-center justify-center rounded-[12px] border border-dashed border-[#e3e7f1] bg-[#fafbfc] px-[16px] text-center text-[12px] text-[#858b9c]">
      {children}
    </p>
  );
}

export default function WorkbenchDashboardPage({
  currentUser,
  onLogout,
}: WorkbenchDashboardPageProps) {
  const [dashboard, setDashboard] = useState<DashboardRead | null>(null);
  const [employees, setEmployees] = useState<EmployeeRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [employeeError, setEmployeeError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setEmployeeError(null);
    const dashboardRequest = workbenchApi.getDashboard(currentUser.tenant_id);
    const employeeRequest = workbenchApi.listEmployees(currentUser.tenant_id);
    void Promise.allSettled([dashboardRequest, employeeRequest]).then(([dashboardResult, employeeResult]) => {
      if (!active) return;
      if (dashboardResult.status === 'rejected') {
        setError(dashboardResult.reason);
        setDashboard(null);
      } else {
        setDashboard(normalizeDashboard(dashboardResult.value));
        if (employeeResult.status === 'fulfilled') {
          setEmployees(Array.isArray(employeeResult.value) ? employeeResult.value : []);
        } else {
          setEmployees([]);
          const expectedMemberDenial = currentUser.role === 'member'
            && employeeResult.reason instanceof ApiError
            && employeeResult.reason.status === 403;
          if (!expectedMemberDenial) setEmployeeError(employeeResult.reason);
        }
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [currentUser.role, currentUser.tenant_id, refreshKey]);

  const employeeByUserId = useMemo(
    () => new Map(employees.map((employee) => [employee.user_id, employee])),
    [employees],
  );
  const self = employeeByUserId.get(currentUser.id);
  const isGlobalView = currentUser.role === 'admin' || self?.business_role === 'ceo';
  const isManagerView = isGlobalView || self?.business_role === 'manager';
  const data = dashboard || EMPTY_DASHBOARD;
  const activeTaskCount = ['backlog', 'blocked', 'in_progress', 'review']
    .reduce((total, status) => total + (data.task_counts[status as keyof typeof data.task_counts] || 0), 0);
  const teamDailyCost = employees.reduce(
    (total, employee) => total + (employee.status === 'active' ? employee.daily_cost || 0 : 0),
    0,
  );
  const hasWork = data.project_count > 0
    || Object.values(data.task_counts).some((count) => Boolean(count))
    || data.recent_events.length > 0;

  return (
    <WorkbenchLayout
      title="企业工作台"
      description={employeeError
        ? '员工与成本数据未完成加载'
        : isGlobalView
          ? '查看公司项目、任务、人员负载与协作动态'
          : '聚焦由你负责的真实工作与协作动态'}
      currentUser={currentUser}
      onLogout={onLogout}
    >
      {loading ? (
        <DashboardLoading />
      ) : error ? (
        <DashboardError
          permissionDenied={error instanceof ApiError && error.status === 403}
          onRetry={() => setRefreshKey((value) => value + 1)}
        />
      ) : employeeError ? (
        <DashboardError
          permissionDenied={false}
          partial
          onRetry={() => setRefreshKey((value) => value + 1)}
        />
      ) : (
        <div className="space-y-[20px]">
          <div className="flex flex-wrap items-end justify-between gap-[12px]">
            <div>
              <h2 className="m-0 text-[18px] font-semibold text-[#24262d]">
                {isGlobalView ? '公司运营概览' : isManagerView ? '部门运营概览' : '我的工作概览'}
              </h2>
              <p className="mt-[5px] mb-0 text-[12px] text-[#858b9c]">数据来自当前可见项目与真人任务记录</p>
            </div>
            <Link to="/enterprise/projects" className="text-[12px] font-medium text-[#1a71ff] hover:underline">
              查看项目中心
            </Link>
          </div>

          <div className="grid grid-cols-1 gap-[14px] sm:grid-cols-2 xl:grid-cols-4">
            {isManagerView ? (
              <>
                <WorkbenchKpi label="项目总数" value={data.project_count} supporting="当前权限范围" icon={<BriefcaseBusiness className="size-[18px]" />} />
                <WorkbenchKpi label="执行中任务" value={activeTaskCount} supporting="含待办、阻塞、进行中与审核" icon={<ListTodo className="size-[18px]" />} tone="green" />
                <WorkbenchKpi label="待审核任务" value={data.pending_review_count} supporting="等待真人负责人确认" icon={<ClipboardCheck className="size-[18px]" />} tone="orange" />
                {isGlobalView ? (
                  <WorkbenchKpi label="团队日成本" value={formatCurrency(teamDailyCost)} supporting={`${data.employee_count} 名在岗员工`} icon={<Coins className="size-[18px]" />} tone="gray" />
                ) : (
                  <WorkbenchKpi label="可见员工" value={data.employee_count} supporting="当前部门范围" icon={<UsersRound className="size-[18px]" />} tone="gray" />
                )}
              </>
            ) : (
              <>
                <WorkbenchKpi label="我的进行中" value={data.task_counts.in_progress || 0} supporting="正在推进" icon={<Clock3 className="size-[18px]" />} />
                <WorkbenchKpi label="待审核" value={data.task_counts.review || 0} supporting="已提交、等待审核" icon={<ClipboardCheck className="size-[18px]" />} tone="orange" />
                <WorkbenchKpi label="逾期任务" value={data.at_risk_tasks.length} supporting="需要优先处理" icon={<CircleAlert className="size-[18px]" />} tone="red" />
                <WorkbenchKpi label="我的待办" value={data.task_counts.backlog || 0} supporting="可以开始执行" icon={<ListTodo className="size-[18px]" />} tone="gray" />
              </>
            )}
          </div>

          {!hasWork && (
            <section className="rounded-[16px] border border-dashed border-[#ccd5e5] bg-[#fafdff] px-[24px] py-[26px] text-center">
              <BriefcaseBusiness className="mx-auto size-[26px] text-[#9aa8bf]" aria-hidden="true" />
              <h3 className="mt-[10px] mb-0 text-[14px] font-semibold text-[#464c5e]">还没有项目或任务数据</h3>
              <p className="mt-[5px] mb-0 text-[12px] text-[#858b9c]">创建项目或接收任务后，这里会展示真实运营进展。</p>
            </section>
          )}

          <div className="grid grid-cols-1 gap-[18px] xl:grid-cols-2">
            {isManagerView && (
              <Panel title="待审核事项">
                {data.pending_reviews.length === 0 ? (
                  <EmptyLine>暂无待审核任务</EmptyLine>
                ) : (
                  <div className="space-y-[10px]">
                    {data.pending_reviews.map((task) => (
                      <TaskRow key={task.id} task={task} employee={task.assignee_user_id ? employeeByUserId.get(task.assignee_user_id) : undefined} />
                    ))}
                  </div>
                )}
              </Panel>
            )}

            <Panel title="人员负载">
              {data.workload_rows.length === 0 ? (
                <EmptyLine>暂无人员负载数据</EmptyLine>
              ) : (
                <div className="space-y-[14px]">
                  {data.workload_rows.map((row) => (
                    <WorkloadRowView
                      key={row.user_id}
                      row={row}
                      employee={employeeByUserId.get(row.user_id)}
                      currentUser={currentUser}
                    />
                  ))}
                </div>
              )}
            </Panel>

            {isManagerView && (
              <Panel title="项目健康">
                {data.project_summaries.length === 0 ? (
                  <EmptyLine>暂无项目健康数据</EmptyLine>
                ) : (
                  <div className="space-y-[10px]">
                    {data.project_summaries.map((project) => (
                      <ProjectHealthRow key={project.id} project={project} />
                    ))}
                  </div>
                )}
              </Panel>
            )}

            <Panel title="风险提醒">
              {data.at_risk_tasks.length === 0 ? (
                <EmptyLine>暂无风险任务</EmptyLine>
              ) : (
                <div className="space-y-[10px]">
                  {data.at_risk_tasks.map((task) => (
                    <TaskRow key={task.id} task={task} employee={task.assignee_user_id ? employeeByUserId.get(task.assignee_user_id) : undefined} risk />
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="近期动态">
              {data.recent_events.length === 0 ? (
                <EmptyLine>暂无近期动态</EmptyLine>
              ) : (
                <ol className="m-0 space-y-[12px] p-0">
                  {data.recent_events.map((event) => (
                    <li key={event.id} className="flex gap-[10px]">
                      <span className="mt-[4px] flex size-[26px] shrink-0 items-center justify-center rounded-[8px] bg-[#eef4ff] text-[#1a71ff]">
                        <Activity className="size-[13px]" aria-hidden="true" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-[12px] font-medium leading-[18px] text-[#464c5e]">{eventLabel(event, employeeByUserId)}</span>
                        <span className="block text-[11px] leading-[17px] text-[#9aa1b3]">{formatDateTime(event.created_at)}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </Panel>
          </div>
        </div>
      )}
    </WorkbenchLayout>
  );
}

function TaskRow({ task, employee, risk = false }: { task: TaskRead; employee?: EmployeeRead; risk?: boolean }) {
  return (
    <Link
      to={`/enterprise/tasks/${encodeURIComponent(task.id)}`}
      className="flex min-w-0 items-center justify-between gap-[14px] rounded-[12px] border border-[#edf0f5] px-[14px] py-[12px] transition-colors hover:bg-[#fafbfc]"
    >
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-medium text-[#24262d]">{task.title}</span>
        <span className="mt-[4px] block text-[11px] text-[#858b9c]">
          {risk && task.due_date ? `截止 ${task.due_date} · 已逾期` : taskStatusLabel(task.status)}
        </span>
      </span>
      <EmployeeBadgeContainer employee={employee} userId={task.assignee_user_id || undefined} compact subtitle={null} />
    </Link>
  );
}

function WorkloadRowView({
  row,
  employee,
  currentUser,
}: {
  row: WorkloadRow;
  employee?: EmployeeRead;
  currentUser: EnterpriseAuthUser;
}) {
  const fallbackName = row.user_id === currentUser.id
    ? currentUser.display_name || currentUser.username
    : row.user_id;
  return (
    <div className="grid min-w-0 gap-[10px] rounded-[12px] border border-[#edf0f5] px-[14px] py-[12px] sm:grid-cols-[minmax(130px,0.75fr)_minmax(180px,1.25fr)] sm:items-center">
      <EmployeeBadgeContainer employee={employee} userId={row.user_id} name={fallbackName} compact />
      <WorkloadBar
        value={row.capacity_percent}
        detail={`负载 ${formatWorkload(row)} · ${row.active_task_count} 项进行中`}
      />
    </div>
  );
}

function ProjectHealthRow({ project }: { project: ProjectRead }) {
  const health = PROJECT_HEALTH[project.health];
  const progress = projectProgress(project);
  return (
    <article aria-label={project.name} className="rounded-[12px] border border-[#edf0f5] px-[14px] py-[12px]">
      <div className="flex items-center justify-between gap-[12px]">
        <span className="min-w-0 truncate text-[13px] font-medium text-[#24262d]">{project.name}</span>
        <span className={`shrink-0 rounded-full px-[9px] py-[3px] text-[10px] font-medium ${health.className}`}>
          {health.label}
        </span>
      </div>
      <div className="mt-[10px] flex items-center gap-[10px]">
        <div className="h-[6px] min-w-0 flex-1 overflow-hidden rounded-full bg-[#edf0f5]">
          <span className="block h-full rounded-full bg-[#1a71ff]" style={{ width: `${progress}%` }} />
        </div>
        <span className="w-[34px] text-right text-[11px] font-medium text-[#596176]">{progress}%</span>
      </div>
    </article>
  );
}
