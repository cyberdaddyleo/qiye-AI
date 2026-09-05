import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckSquare2, CircleAlert, Clock3, ListChecks } from 'lucide-react';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { formatDateTime } from '@/lib/enterprise-ui';
import type {
  DashboardRead,
  EmployeeRead,
  ProjectRead,
  ReviewVerdict,
  TaskRead,
  WorkTaskEventRead,
  WorkbenchAccessRead,
} from '@/types/workbench';

import WorkbenchLayout from './WorkbenchLayout';
import { workbenchApi } from './workbenchApi';
import { isTaskOverdue } from './workbenchDate';
import TaskCard from './components/TaskCard';
import TaskDetailSheet from './components/TaskDetailSheet';
import WorkbenchKpi from './components/WorkbenchKpi';
import WorkloadBar from './components/WorkloadBar';

export type MyWorkPageProps = {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
  now?: Date;
  timeZone?: string;
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

const PRIORITY_ORDER: Record<TaskRead['priority'], number> = {
  urgent: 0,
  high: 1,
  normal: 2,
  low: 3,
};

const EVENT_ACTION: Record<string, string> = {
  task_created: '创建了任务',
  task_assigned: '分配了任务',
  task_started: '开始了任务',
  task_updated: '更新了任务',
  progress_updated: '更新了进度',
  comment_added: '添加了评论',
  result_submitted: '提交了成果',
  review_approved: '通过了任务',
  review_returned: '退回了任务',
  dependency_unblocked: '解锁了任务',
};

function roleHeadline(access: WorkbenchAccessRead, currentUser: EnterpriseAuthUser): string {
  const name = currentUser.display_name || currentUser.username;
  if (access.business_role === 'admin' || access.business_role === 'ceo') {
    return `${name}，这是你的管理与审核重点`;
  }
  if (access.business_role === 'manager') return `${name}，先处理团队审核与关键任务`;
  return `${name}，今天先完成最重要的工作`;
}

function eventLabel(
  event: WorkTaskEventRead,
  currentUser: EnterpriseAuthUser,
  employees: Map<string, EmployeeRead>,
): string {
  const actor = event.actor_user_id ? employees.get(event.actor_user_id) : undefined;
  const name = event.actor_user_id === currentUser.id
    ? currentUser.display_name || currentUser.username
    : actor?.display_name || actor?.username || (event.actor_type === 'system' ? '系统' : '真人成员');
  return `${name}${EVENT_ACTION[event.event_type] || '更新了工作动态'}`;
}

export default function MyWorkPage({
  currentUser,
  onLogout,
  now,
  timeZone,
}: MyWorkPageProps) {
  const [access, setAccess] = useState<WorkbenchAccessRead | null>(null);
  const [dashboard, setDashboard] = useState<DashboardRead>(EMPTY_DASHBOARD);
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [employees, setEmployees] = useState<EmployeeRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTaskId, setDetailTaskId] = useState('');
  const [detailTask, setDetailTask] = useState<TaskRead | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [conflictMessage, setConflictMessage] = useState('');
  const [, setClockRevision] = useState(0);

  useEffect(() => {
    if (now) return undefined;
    const timer = window.setInterval(() => {
      setClockRevision((value) => value + 1);
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [now]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailure(null);
    void Promise.allSettled([
      workbenchApi.getAccess(currentUser.tenant_id),
      workbenchApi.getDashboard(currentUser.tenant_id),
      workbenchApi.listTasks({ tenant_id: currentUser.tenant_id, scope: 'mine' }),
      workbenchApi.listProjects(currentUser.tenant_id),
      workbenchApi.listEmployees(currentUser.tenant_id),
    ]).then(([accessResult, dashboardResult, tasksResult, projectsResult, employeesResult]) => {
      if (!active) return;
      if (accessResult.status === 'rejected') {
        setFailure(accessResult.reason);
      } else if (dashboardResult.status === 'rejected') {
        setFailure(dashboardResult.reason);
      } else if (tasksResult.status === 'rejected') {
        setFailure(tasksResult.reason);
      } else if (projectsResult.status === 'rejected') {
        setFailure(projectsResult.reason);
      } else {
        const expectedMemberDenial = accessResult.value.business_role === 'member'
          && employeesResult.status === 'rejected'
          && employeesResult.reason instanceof ApiError
          && employeesResult.reason.status === 403;
        if (employeesResult.status === 'rejected' && !expectedMemberDenial) {
          setFailure(employeesResult.reason);
        } else {
          setAccess(accessResult.value);
          setDashboard({
            ...EMPTY_DASHBOARD,
            ...dashboardResult.value,
            task_counts: dashboardResult.value.task_counts || {},
            workload_rows: Array.isArray(dashboardResult.value.workload_rows) ? dashboardResult.value.workload_rows : [],
            recent_events: Array.isArray(dashboardResult.value.recent_events) ? dashboardResult.value.recent_events : [],
          });
          setTasks(Array.isArray(tasksResult.value) ? tasksResult.value : []);
          setProjects(Array.isArray(projectsResult.value) ? projectsResult.value : []);
          setEmployees(employeesResult.status === 'fulfilled' && Array.isArray(employeesResult.value) ? employeesResult.value : []);
        }
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [currentUser.id, currentUser.tenant_id, reloadKey]);

  const employeeByUserId = useMemo(
    () => new Map(employees.map((employee) => [employee.user_id, employee])),
    [employees],
  );
  const projectById = useMemo(
    () => new Map(projects.map((project) => [project.id, project])),
    [projects],
  );
  const businessNow = now || new Date();
  const executionTasks = tasks.filter((task) => task.assignee_user_id === currentUser.id);
  const reviewTasks = tasks.filter((task) => task.reviewer_user_id === currentUser.id);
  const inProgress = executionTasks.filter((task) => task.status === 'in_progress');
  const inReview = reviewTasks.filter((task) => task.status === 'review');
  const overdue = executionTasks.filter((task) => (
    isTaskOverdue(task.due_date, task.status, { now: businessNow, timeZone })
  ));
  const priorities = [...executionTasks]
    .filter((task) => task.status !== 'done' && task.status !== 'canceled')
    .sort((left, right) => (
      PRIORITY_ORDER[left.priority] - PRIORITY_ORDER[right.priority]
      || (left.due_date || '9999-12-31').localeCompare(right.due_date || '9999-12-31')
      || left.title.localeCompare(right.title)
    ))
    .slice(0, 5);
  const workload = dashboard.workload_rows.find((row) => row.user_id === currentUser.id);
  const hasWork = tasks.length > 0 || dashboard.recent_events.length > 0;

  async function openTask(taskId: string) {
    setDetailOpen(true);
    setDetailTaskId(taskId);
    setDetailLoading(true);
    setDetailError(null);
    setActionError('');
    setConflictMessage('');
    try {
      setDetailTask(await workbenchApi.getTask(taskId, currentUser.tenant_id));
    } catch (caught) {
      setDetailTask(null);
      setDetailError(caught);
    } finally {
      setDetailLoading(false);
    }
  }

  async function refetchTaskState(taskId: string) {
    const [detailResult, tasksResult, dashboardResult] = await Promise.allSettled([
      workbenchApi.getTask(taskId, currentUser.tenant_id),
      workbenchApi.listTasks({ tenant_id: currentUser.tenant_id, scope: 'mine' }),
      workbenchApi.getDashboard(currentUser.tenant_id),
    ]);
    if (detailResult.status === 'fulfilled') {
      setDetailTask(detailResult.value);
      setDetailError(null);
    } else {
      setDetailError(detailResult.reason);
    }
    if (tasksResult.status === 'fulfilled') setTasks(Array.isArray(tasksResult.value) ? tasksResult.value : []);
    else setFailure(tasksResult.reason);
    if (dashboardResult.status === 'fulfilled') {
      setDashboard({
        ...EMPTY_DASHBOARD,
        ...dashboardResult.value,
        task_counts: dashboardResult.value.task_counts || {},
        workload_rows: Array.isArray(dashboardResult.value.workload_rows) ? dashboardResult.value.workload_rows : [],
        recent_events: Array.isArray(dashboardResult.value.recent_events) ? dashboardResult.value.recent_events : [],
      });
    } else setFailure(dashboardResult.reason);
  }

  async function mutateTask(run: (task: TaskRead) => Promise<TaskRead>): Promise<boolean> {
    if (!detailTask || actionBusy) return false;
    const taskAtIntent = detailTask;
    setActionBusy(true);
    setActionError('');
    setConflictMessage('');
    try {
      await run(taskAtIntent);
      await refetchTaskState(taskAtIntent.id);
      return true;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        await refetchTaskState(taskAtIntent.id);
        setConflictMessage('任务版本冲突，已刷新最新状态。请根据服务端最新内容重新操作。');
      } else if (caught instanceof ApiError && caught.status === 403) {
        setActionError('操作被拒绝：当前账号没有此任务操作权限。');
      } else if (caught instanceof ApiError && caught.status >= 400 && caught.status < 500) {
        setActionError('任务操作失败，请检查输入后重试。');
      } else {
        await refetchTaskState(taskAtIntent.id);
        setActionError('任务操作结果未知，已刷新服务端状态；请核对后再重试。');
      }
      return false;
    } finally {
      setActionBusy(false);
    }
  }

  return (
    <WorkbenchLayout
      title="员工工作台"
      description="聚焦真人员工的优先事项、交付、审核与协作动态"
      currentUser={currentUser}
      onLogout={onLogout}
    >
      {loading ? (
        <div role="status" aria-label="员工工作台加载中" className="space-y-[16px]">
          <Skeleton className="h-[72px] rounded-[16px] bg-[#e9edf4]" />
          <div className="grid gap-[12px] sm:grid-cols-3">{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-[120px] rounded-[16px] bg-[#e9edf4]" />)}</div>
        </div>
      ) : failure ? (
        <section role="alert" className="rounded-[16px] border border-[#f1d4d4] bg-white px-[24px] py-[40px] text-center">
          <CircleAlert className="mx-auto size-[27px] text-[#d20b0b]" aria-hidden="true" />
          <h2 className="mt-[11px] mb-0 text-[15px] font-semibold text-[#24262d]">{failure instanceof ApiError && failure.status === 403 ? '无权查看员工工作台' : '员工工作台加载失败'}</h2>
          <p className="mt-[6px] mb-0 text-[11px] text-[#757f9c]">无法读取服务端最新个人任务与协作数据。</p>
          <Button type="button" onClick={() => setReloadKey((value) => value + 1)} className="mt-[15px] h-[33px] rounded-[9px] bg-[#18181a] px-[16px] text-[11px] text-white">重试</Button>
        </section>
      ) : access && !hasWork ? (
        <section className="rounded-[16px] border border-dashed border-[#ccd5e5] bg-white px-[24px] py-[48px] text-center">
          <CheckSquare2 className="mx-auto size-[29px] text-[#2cb360]" aria-hidden="true" />
          <h2 className="mt-[12px] mb-0 text-[15px] font-semibold text-[#464c5e]">今天没有待处理工作</h2>
          <p className="mt-[6px] mb-0 text-[12px] text-[#858b9c]">新的任务、审核或协作动态会在这里出现。</p>
        </section>
      ) : access ? (
        <div className="space-y-[18px]">
          <section className="rounded-[16px] border border-[#dfe6f2] bg-[linear-gradient(120deg,#ffffff_0%,#f2f7ff_100%)] px-[20px] py-[18px]">
            <h2 className="m-0 text-[17px] font-semibold text-[#24262d]">{roleHeadline(access, currentUser)}</h2>
            <p className="mt-[6px] mb-0 text-[11px] leading-[18px] text-[#757f9c]">任务责任与审核归属于真人员工；AI 助理仅帮助拆解、推荐与总结。</p>
          </section>

          <section className="grid grid-cols-1 gap-[12px] sm:grid-cols-3">
            <WorkbenchKpi label="进行中" value={inProgress.length} supporting="正在由你推进" icon={<ListChecks className="size-[17px]" />} tone="blue" />
            <WorkbenchKpi label="待审核" value={inReview.length} supporting="已提交、等待真人审核" icon={<Clock3 className="size-[17px]" />} tone="orange" />
            <WorkbenchKpi label="已逾期" value={overdue.length} supporting="需要优先处理或沟通" icon={<AlertTriangle className="size-[17px]" />} tone="red" />
          </section>

          <div className="grid gap-[18px] xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.8fr)]">
            <Panel title="今日优先">
              {priorities.length ? (
                <div className="grid gap-[10px] md:grid-cols-2">
                  {priorities.map((task) => <TaskCard key={task.id} task={task} project={projectById.get(task.project_id)} assignee={employeeByUserId.get(task.assignee_user_id || '')} onOpen={(taskId) => void openTask(taskId)} now={businessNow} timeZone={timeZone} />)}
                </div>
              ) : <EmptyLine>今天没有需要推进的任务。</EmptyLine>}
            </Panel>

            <div className="space-y-[18px]">
              <Panel title="我的负载">
                {workload ? (
                  <div className="space-y-[11px]">
                    <WorkloadBar value={workload.capacity_percent} label="可用容量" detail="个人可用容量" />
                    <p className="m-0 text-[11px] text-[#757f9c]">{workload.estimate_days} 人日 · {workload.active_task_count} 项未完成任务</p>
                  </div>
                ) : <EmptyLine>暂无个人负载数据。</EmptyLine>}
              </Panel>

              <Panel title="待提交成果">
                {inProgress.length ? (
                  <div className="space-y-[7px]">
                    {inProgress.map((task) => (
                      <button key={task.id} type="button" onClick={() => void openTask(task.id)} className="flex w-full items-center justify-between gap-[8px] rounded-[9px] border border-[#edf0f5] px-[10px] py-[9px] text-left text-[11px] text-[#596176] hover:bg-[#f7f9fc]">
                        <span className="truncate">{task.title}</span>
                        <span className="shrink-0 text-[9px] text-[#9aa1b3]">{task.due_date || '日期待定'}</span>
                      </button>
                    ))}
                  </div>
                ) : <EmptyLine>没有待提交成果。</EmptyLine>}
              </Panel>

              <Panel title="待我审核">
                {inReview.length ? (
                  <div className="space-y-[7px]">
                    {inReview.map((task) => (
                      <button key={task.id} type="button" onClick={() => void openTask(task.id)} className="flex w-full items-center justify-between gap-[8px] rounded-[9px] border border-[#edf0f5] px-[10px] py-[9px] text-left text-[11px] text-[#596176] hover:bg-[#f7f9fc]">
                        <span className="truncate">{task.title}</span>
                        <span className="shrink-0 text-[9px] text-[#9aa1b3]">等待真人审核</span>
                      </button>
                    ))}
                  </div>
                ) : <EmptyLine>没有待审核成果。</EmptyLine>}
              </Panel>
            </div>
          </div>

          <Panel title="最近协作动态">
            {dashboard.recent_events.length ? (
              <ol className="m-0 grid gap-[9px] p-0 md:grid-cols-2">
                {dashboard.recent_events.slice(0, 8).map((event) => (
                  <li key={event.id} className="list-none rounded-[10px] border border-[#edf0f5] px-[11px] py-[9px]">
                    <p className="m-0 text-[11px] font-medium text-[#464c5e]">{eventLabel(event, currentUser, employeeByUserId)}</p>
                    <time className="mt-[3px] block text-[9px] text-[#9aa1b3]">{formatDateTime(event.created_at)}</time>
                  </li>
                ))}
              </ol>
            ) : <EmptyLine>还没有协作动态。</EmptyLine>}
          </Panel>
        </div>
      ) : null}

      <TaskDetailSheet
        open={detailOpen}
        onOpenChange={setDetailOpen}
        task={detailTask}
        loading={detailLoading}
        error={detailError}
        actionError={actionError}
        conflictMessage={conflictMessage}
        busy={actionBusy}
        currentUser={currentUser}
        access={access}
        employees={employees}
        projects={projects}
        allTasks={tasks}
        onRetry={() => detailTaskId && void openTask(detailTaskId)}
        onOpenTask={(taskId) => void openTask(taskId)}
        onStart={() => mutateTask((task) => workbenchApi.updateTask(task.id, { tenant_id: currentUser.tenant_id, version: task.version, status: 'in_progress' }))}
        onComment={(comment) => mutateTask((task) => workbenchApi.commentTask(task.id, { tenant_id: currentUser.tenant_id, version: task.version, comment }))}
        onSubmit={(resultSummary) => mutateTask((task) => workbenchApi.submitTask(task.id, { tenant_id: currentUser.tenant_id, version: task.version, result_summary: resultSummary, artifact_refs: [] }))}
        onReview={(verdict: ReviewVerdict, comment) => mutateTask((task) => workbenchApi.reviewTask(task.id, { tenant_id: currentUser.tenant_id, version: task.version, verdict, comment: comment || null }))}
      />
    </WorkbenchLayout>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[16px] border border-[#edf0f5] bg-white p-[18px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
      <h3 className="m-0 text-[13px] font-semibold text-[#24262d]">{title}</h3>
      <div className="mt-[13px]">{children}</div>
    </section>
  );
}

function EmptyLine({ children }: { children: React.ReactNode }) {
  return <p className="m-0 rounded-[10px] border border-dashed border-[#e3e7f1] bg-[#fafbfc] px-[12px] py-[24px] text-center text-[11px] text-[#858b9c]">{children}</p>;
}
