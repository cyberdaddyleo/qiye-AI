import { useEffect, useMemo, useState } from 'react';
import { CircleAlert, Filter, LayoutDashboard, RefreshCw } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import type {
  EmployeeRead,
  ProjectRead,
  ReviewVerdict,
  TaskRead,
  TaskScope,
  TaskStatus,
  WorkbenchAccessRead,
} from '@/types/workbench';

import WorkbenchLayout from './WorkbenchLayout';
import { workbenchApi } from './workbenchApi';
import { groupTasksByStatus, taskStatusLabel, WORKBENCH_TASK_STATUSES } from './workbenchModel';
import TaskCard from './components/TaskCard';
import TaskDetailSheet from './components/TaskDetailSheet';

export type TasksPageProps = {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
};

type TaskFilters = {
  scope: TaskScope;
  status: TaskStatus | '';
  projectId: string;
};

type LoadFailure = {
  source: 'access' | 'projects' | 'employees' | 'tasks';
  reason: unknown;
};

const TASK_PAGE_SIZE = 50;

function defaultScope(access: WorkbenchAccessRead): TaskScope {
  if (access.directory_scope === 'all') return 'all';
  if (access.directory_scope === 'department') return 'department';
  return 'mine';
}

function allowedScopes(access: WorkbenchAccessRead | null): Array<{ value: TaskScope; label: string }> {
  const scopes: Array<{ value: TaskScope; label: string }> = [{ value: 'mine', label: '我的任务' }];
  if (access?.directory_scope === 'department') scopes.push({ value: 'department', label: '部门任务' });
  if (access?.directory_scope === 'all') scopes.push({ value: 'all', label: '全部任务' });
  return scopes;
}

export default function TasksPage({ currentUser, onLogout }: TasksPageProps) {
  const [searchParams] = useSearchParams();
  const requestedProjectId = searchParams.get('project_id') || '';
  const requestedTaskId = searchParams.get('task_id') || '';
  const [access, setAccess] = useState<WorkbenchAccessRead | null>(null);
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [employees, setEmployees] = useState<EmployeeRead[]>([]);
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [page, setPage] = useState(0);
  const [totalTasks, setTotalTasks] = useState(0);
  const [filters, setFilters] = useState<TaskFilters>({ scope: 'mine', status: '', projectId: requestedProjectId });
  const [loading, setLoading] = useState(true);
  const [failure, setFailure] = useState<LoadFailure | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTask, setDetailTask] = useState<TaskRead | null>(null);
  const [detailTaskId, setDetailTaskId] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [conflictMessage, setConflictMessage] = useState('');

  useEffect(() => {
    if (requestedTaskId) void openTask(requestedTaskId);
  }, [currentUser.id, currentUser.tenant_id, requestedTaskId]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailure(null);
    void Promise.allSettled([
      workbenchApi.getAccess(currentUser.tenant_id),
      workbenchApi.listProjects(currentUser.tenant_id),
      workbenchApi.listEmployees(currentUser.tenant_id),
    ]).then(async ([accessResult, projectResult, employeeResult]) => {
      if (!active) return;
      if (accessResult.status === 'rejected') {
        setFailure({ source: 'access', reason: accessResult.reason });
        setLoading(false);
        return;
      }
      if (projectResult.status === 'rejected') {
        setFailure({ source: 'projects', reason: projectResult.reason });
        setLoading(false);
        return;
      }
      const memberDirectoryDenial = accessResult.value.business_role === 'member'
        && employeeResult.status === 'rejected'
        && employeeResult.reason instanceof ApiError
        && employeeResult.reason.status === 403;
      if (employeeResult.status === 'rejected' && !memberDirectoryDenial) {
        setFailure({ source: 'employees', reason: employeeResult.reason });
        setLoading(false);
        return;
      }

      const nextProjects = Array.isArray(projectResult.value) ? projectResult.value : [];
      const nextEmployees = employeeResult.status === 'fulfilled' && Array.isArray(employeeResult.value)
        ? employeeResult.value
        : [];
      const scope = defaultScope(accessResult.value);
      const projectId = nextProjects.some((project) => project.id === requestedProjectId)
        ? requestedProjectId
        : '';
      const nextFilters: TaskFilters = { scope, status: '', projectId };
      setAccess(accessResult.value);
      setProjects(nextProjects);
      setEmployees(nextEmployees);
      setFilters(nextFilters);
      setPage(0);
      try {
        const taskPage = await workbenchApi.listTasksPage({
          tenant_id: currentUser.tenant_id,
          scope,
          status: undefined,
          project_id: projectId || undefined,
          limit: TASK_PAGE_SIZE,
          offset: 0,
        });
        if (!active) return;
        setTasks(Array.isArray(taskPage.items) ? taskPage.items : []);
        setTotalTasks(taskPage.total);
      } catch (caught) {
        if (!active) return;
        setFailure({ source: 'tasks', reason: caught });
      } finally {
        if (active) setLoading(false);
      }
    });
    return () => {
      active = false;
    };
  }, [currentUser.id, currentUser.tenant_id, reloadKey, requestedProjectId]);

  const employeeByUserId = useMemo(
    () => new Map(employees.map((employee) => [employee.user_id, employee])),
    [employees],
  );
  const projectById = useMemo(
    () => new Map(projects.map((project) => [project.id, project])),
    [projects],
  );
  const groupedTasks = useMemo(() => groupTasksByStatus(tasks), [tasks]);

  function taskQuery(nextFilters: TaskFilters, pageIndex = page) {
    return {
      tenant_id: currentUser.tenant_id,
      scope: nextFilters.scope,
      status: nextFilters.status || undefined,
      project_id: nextFilters.projectId || undefined,
      limit: TASK_PAGE_SIZE,
      offset: pageIndex * TASK_PAGE_SIZE,
    };
  }

  async function applyFilters(nextFilters: TaskFilters) {
    setFilters(nextFilters);
    setPage(0);
    setLoading(true);
    setFailure(null);
    try {
      const taskPage = await workbenchApi.listTasksPage(taskQuery(nextFilters, 0));
      setTasks(Array.isArray(taskPage.items) ? taskPage.items : []);
      setTotalTasks(taskPage.total);
    } catch (caught) {
      setFailure({ source: 'tasks', reason: caught });
    } finally {
      setLoading(false);
    }
  }

  async function changePage(nextPage: number) {
    if (nextPage < 0 || nextPage === page) return;
    setLoading(true);
    setFailure(null);
    try {
      const taskPage = await workbenchApi.listTasksPage(taskQuery(filters, nextPage));
      setTasks(Array.isArray(taskPage.items) ? taskPage.items : []);
      setTotalTasks(taskPage.total);
      setPage(nextPage);
    } catch (caught) {
      setFailure({ source: 'tasks', reason: caught });
    } finally {
      setLoading(false);
    }
  }

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
    const [detailResult, listResult] = await Promise.allSettled([
      workbenchApi.getTask(taskId, currentUser.tenant_id),
      workbenchApi.listTasksPage(taskQuery(filters)),
    ]);
    if (detailResult.status === 'fulfilled') {
      setDetailTask(detailResult.value);
      setDetailError(null);
    } else {
      setDetailError(detailResult.reason);
    }
    if (listResult.status === 'fulfilled') {
      setTasks(Array.isArray(listResult.value.items) ? listResult.value.items : []);
      setTotalTasks(listResult.value.total);
      setFailure(null);
    } else {
      setFailure({ source: 'tasks', reason: listResult.reason });
    }
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
      title="任务中心"
      description="看板状态、依赖、提交与审核均以服务端最新记录为准"
      currentUser={currentUser}
      onLogout={onLogout}
      actions={!loading && !failure ? (
        <Button type="button" variant="outline" onClick={() => setReloadKey((value) => value + 1)} className="h-[34px] gap-[5px] rounded-[10px] border-[#e3e7f1] px-[12px] text-[11px] text-[#596176]">
          <RefreshCw className="size-[13px]" aria-hidden="true" />刷新
        </Button>
      ) : undefined}
    >
      <section aria-label="任务筛选" className="mb-[16px] flex flex-wrap items-end gap-[10px] rounded-[14px] border border-[#e8ebf2] bg-white px-[14px] py-[12px]">
        <span className="mb-[8px] flex items-center gap-[5px] text-[11px] font-medium text-[#596176]"><Filter className="size-[12px]" aria-hidden="true" />筛选</span>
        <FilterField label="任务范围">
          <select value={filters.scope} disabled={loading || !access} onChange={(event) => void applyFilters({ ...filters, scope: event.target.value as TaskScope })} className="h-[33px] min-w-[120px] rounded-[9px] border border-[#e3e7f1] bg-white px-[9px] text-[11px] text-[#464c5e] outline-none focus:border-[#18181a]">
            {allowedScopes(access).map((scope) => <option key={scope.value} value={scope.value}>{scope.label}</option>)}
          </select>
        </FilterField>
        <FilterField label="状态筛选">
          <select value={filters.status} disabled={loading || !access} onChange={(event) => void applyFilters({ ...filters, status: event.target.value as TaskStatus | '' })} className="h-[33px] min-w-[120px] rounded-[9px] border border-[#e3e7f1] bg-white px-[9px] text-[11px] text-[#464c5e] outline-none focus:border-[#18181a]">
            <option value="">全部状态</option>
            {WORKBENCH_TASK_STATUSES.map((status) => <option key={status} value={status}>{taskStatusLabel(status)}</option>)}
          </select>
        </FilterField>
        <FilterField label="项目筛选">
          <select value={filters.projectId} disabled={loading || !access} onChange={(event) => void applyFilters({ ...filters, projectId: event.target.value })} className="h-[33px] min-w-[150px] max-w-[240px] rounded-[9px] border border-[#e3e7f1] bg-white px-[9px] text-[11px] text-[#464c5e] outline-none focus:border-[#18181a]">
            <option value="">全部项目</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </FilterField>
      </section>

      {loading ? (
        <div role="status" aria-label="任务加载中" className="flex min-w-[1020px] gap-[12px] overflow-hidden">
          {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-[360px] w-[250px] shrink-0 rounded-[14px] bg-[#e9edf4]" />)}
        </div>
      ) : failure ? (
        <TaskLoadError failure={failure} onRetry={() => setReloadKey((value) => value + 1)} />
      ) : tasks.length === 0 ? (
        <section className="rounded-[16px] border border-dashed border-[#ccd5e5] bg-white px-[24px] py-[48px] text-center">
          <LayoutDashboard className="mx-auto size-[29px] text-[#9aa8bf]" aria-hidden="true" />
          <h2 className="mt-[12px] mb-0 text-[15px] font-semibold text-[#464c5e]">当前筛选下没有任务</h2>
          <p className="mt-[6px] mb-0 text-[12px] text-[#858b9c]">调整范围、项目或状态筛选后再查看。</p>
        </section>
      ) : (
        <section role="region" aria-label="任务看板" className="overflow-x-auto pb-[8px]">
          <div className="grid min-w-[1540px] grid-cols-6 gap-[12px]">
            {WORKBENCH_TASK_STATUSES.map((status) => (
              <section key={status} role="region" aria-label={`${taskStatusLabel(status)}任务列`} className="min-w-0 rounded-[14px] border border-[#e8ebf2] bg-[#f1f4f9] p-[10px]">
                <div className="mb-[10px] flex items-center justify-between px-[3px]">
                  <h2 className="m-0 text-[12px] font-semibold text-[#464c5e]">{taskStatusLabel(status)}</h2>
                  <span className="flex min-w-[20px] items-center justify-center rounded-full bg-white px-[6px] py-[2px] text-[9px] text-[#858b9c]">{groupedTasks[status].length}</span>
                </div>
                <div className="space-y-[9px]">
                  {groupedTasks[status].length ? groupedTasks[status].map((task) => (
                    <TaskCard key={task.id} task={task} project={projectById.get(task.project_id)} assignee={employeeByUserId.get(task.assignee_user_id || '')} onOpen={(taskId) => void openTask(taskId)} />
                  )) : <p className="m-0 rounded-[10px] border border-dashed border-[#dfe4ed] bg-white/55 px-[8px] py-[22px] text-center text-[9px] text-[#9aa1b3]">暂无任务</p>}
                </div>
              </section>
            ))}
          </div>
        </section>
      )}

      {!loading && !failure && (
        <nav aria-label="任务分页" className="mt-[12px] flex flex-wrap items-center justify-end gap-[8px]">
          <span className="mr-auto text-[10px] text-[#858b9c]">第 {page + 1} 页 · 共 {totalTasks} 项任务</span>
          <Button type="button" variant="outline" disabled={page === 0} onClick={() => void changePage(page - 1)} className="h-[31px] rounded-[8px] border-[#dce2ec] px-[12px] text-[10px] text-[#596176]">上一页</Button>
          <Button type="button" variant="outline" disabled={(page + 1) * TASK_PAGE_SIZE >= totalTasks} onClick={() => void changePage(page + 1)} className="h-[31px] rounded-[8px] border-[#dce2ec] px-[12px] text-[10px] text-[#596176]">下一页</Button>
        </nav>
      )}

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
        onStart={() => mutateTask((task) => workbenchApi.updateTask(task.id, {
          tenant_id: currentUser.tenant_id,
          version: task.version,
          status: 'in_progress',
        }))}
        onProgress={(progress) => mutateTask((task) => workbenchApi.updateTask(task.id, {
          tenant_id: currentUser.tenant_id,
          version: task.version,
          progress,
        }))}
        onComment={(comment) => mutateTask((task) => workbenchApi.commentTask(task.id, {
          tenant_id: currentUser.tenant_id,
          version: task.version,
          comment,
        }))}
        onSubmit={(resultSummary, artifactRefs) => mutateTask((task) => workbenchApi.submitTask(task.id, {
          tenant_id: currentUser.tenant_id,
          version: task.version,
          result_summary: resultSummary,
          artifact_refs: artifactRefs,
        }))}
        onReview={(verdict: ReviewVerdict, comment) => mutateTask((task) => workbenchApi.reviewTask(task.id, {
          tenant_id: currentUser.tenant_id,
          version: task.version,
          verdict,
          comment: comment || null,
        }))}
      />
    </WorkbenchLayout>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-[5px]">
      <span className="text-[9px] font-medium text-[#9aa1b3]">{label}</span>
      {children}
    </label>
  );
}

function TaskLoadError({ failure, onRetry }: { failure: LoadFailure; onRetry: () => void }) {
  const denied = failure.reason instanceof ApiError && failure.reason.status === 403;
  const dependencyLabel = failure.source === 'employees'
    ? '真人员工目录'
    : failure.source === 'projects'
      ? '项目目录'
      : failure.source === 'access'
        ? '权限信息'
        : '任务';
  return (
    <section role="alert" className="rounded-[16px] border border-[#f1d4d4] bg-white px-[24px] py-[38px] text-center">
      <CircleAlert className="mx-auto size-[27px] text-[#d20b0b]" aria-hidden="true" />
      <h2 className="mt-[11px] mb-0 text-[15px] font-semibold text-[#24262d]">{denied ? '无权查看任务中心' : '任务加载失败'}</h2>
      <p className="mt-[6px] mb-0 text-[11px] leading-[18px] text-[#757f9c]">{denied ? `当前账号无法读取所需的${dependencyLabel}范围。` : `${dependencyLabel}数据暂时不可用，请稍后重试。`}</p>
      <Button type="button" onClick={onRetry} className="mt-[15px] h-[33px] rounded-[9px] bg-[#18181a] px-[16px] text-[11px] text-white hover:bg-[#303030]">重试</Button>
    </section>
  );
}
