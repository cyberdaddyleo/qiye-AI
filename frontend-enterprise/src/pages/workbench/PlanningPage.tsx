import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, CircleAlert, Sparkles } from 'lucide-react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import type {
  EmployeeRead,
  PlanningTask,
  PlanRead,
  PlanVariant,
  PlanVariantKey,
  ProjectRead,
  WorkbenchAccessRead,
} from '@/types/workbench';

import WorkbenchLayout from './WorkbenchLayout';
import { workbenchApi } from './workbenchApi';
import PlanComparison from './components/PlanComparison';

export type PlanningPageProps = {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
};

type PlanningForm = {
  projectId: string;
  goal: string;
  deadline: string;
  budget: string;
  constraints: string;
};

const EMPTY_FORM: PlanningForm = {
  projectId: '',
  goal: '',
  deadline: '',
  budget: '',
  constraints: '',
};

function cloneVariants(variants: PlanVariant[]): PlanVariant[] {
  return variants.map((variant) => ({
    ...variant,
    metrics: { ...variant.metrics },
    risks: [...variant.risks],
    utilization: Object.fromEntries(
      Object.entries(variant.utilization).map(([key, value]) => [key, { ...value }]),
    ),
    tasks: variant.tasks.map((task) => ({
      ...task,
      skills: [...task.skills],
      depends_on: [...task.depends_on],
      assignment: { ...task.assignment },
    })),
  }));
}

function createDispatchKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `workbench-plan-${crypto.randomUUID()}`;
  }
  return `workbench-plan-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function formatCurrency(value: unknown): string {
  const amount = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(amount)}`;
}

function canPlanProject(
  access: WorkbenchAccessRead,
  project: ProjectRead,
  currentUserId: string,
): boolean {
  return access.can_view_all
    || project.owner_user_id === currentUserId
    || Boolean(
      project.department_id
      && access.managed_department_ids.includes(project.department_id),
    );
}

function dispatchTasks(variant: PlanVariant) {
  return variant.tasks.map((task) => ({
    key: task.key,
    assignee_user_id: task.assignee_user_id,
    start_date: task.start_date,
    due_date: task.due_date,
    acceptance_criteria: task.acceptance_criteria,
    depends_on: [...task.depends_on],
  }));
}

export default function PlanningPage({ currentUser, onLogout }: PlanningPageProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const requestedProjectId = searchParams.get('project_id') || '';
  const [access, setAccess] = useState<WorkbenchAccessRead | null>(null);
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [employees, setEmployees] = useState<EmployeeRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [form, setForm] = useState<PlanningForm>(EMPTY_FORM);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [plan, setPlan] = useState<PlanRead | null>(null);
  const [originalVariants, setOriginalVariants] = useState<PlanVariant[]>([]);
  const [variants, setVariants] = useState<PlanVariant[]>([]);
  const [selectedVariantKey, setSelectedVariantKey] = useState<PlanVariantKey>('A');
  const [confirmed, setConfirmed] = useState(false);
  const [dispatchKey, setDispatchKey] = useState('');
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState('');
  const [dispatchConflict, setDispatchConflict] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(null);
    void Promise.allSettled([
      workbenchApi.getAccess(currentUser.tenant_id),
      workbenchApi.listProjects(currentUser.tenant_id),
      workbenchApi.listEmployees(currentUser.tenant_id),
    ]).then(([accessResult, projectsResult, employeesResult]) => {
      if (!active) return;
      if (accessResult.status === 'rejected') {
        setLoadError(accessResult.reason);
        setAccess(null);
      } else {
        setAccess(accessResult.value);
        if (projectsResult.status === 'rejected') {
          setLoadError(projectsResult.reason);
        } else if (accessResult.value.directory_scope !== 'self' && employeesResult.status === 'rejected') {
          setLoadError(employeesResult.reason);
        } else {
          const activeProjects = (Array.isArray(projectsResult.value) ? projectsResult.value : [])
            .filter((project) => project.status === 'active');
          setProjects(activeProjects);
          setEmployees(
            employeesResult.status === 'fulfilled' && Array.isArray(employeesResult.value)
              ? employeesResult.value.filter((employee) => employee.status === 'active')
              : [],
          );
          const plannableProjects = activeProjects.filter((project) => (
            canPlanProject(accessResult.value, project, currentUser.id)
          ));
          const initialProject = plannableProjects.some((project) => project.id === requestedProjectId)
            ? requestedProjectId
            : plannableProjects[0]?.id || '';
          setForm((value) => ({ ...value, projectId: initialProject }));
        }
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [currentUser.id, currentUser.tenant_id, refreshKey, requestedProjectId]);

  const selectedVariant = useMemo(
    () => variants.find((variant) => variant.key === selectedVariantKey) || variants[0],
    [selectedVariantKey, variants],
  );
  const plannableProjects = useMemo(
    () => access
      ? projects.filter((project) => canPlanProject(access, project, currentUser.id))
      : [],
    [access, currentUser.id, projects],
  );
  const editedVariantKeys = useMemo(() => {
    if (!plan || originalVariants.length === 0) return [];
    return variants
      .filter((variant) => {
        const original = originalVariants.find((candidate) => candidate.key === variant.key);
        return !original
          || JSON.stringify(dispatchTasks(original)) !== JSON.stringify(dispatchTasks(variant));
      })
      .map((variant) => variant.key);
  }, [originalVariants, plan, variants]);
  const selectedVariantEdited = Boolean(
    selectedVariant && editedVariantKeys.includes(selectedVariant.key),
  );

  async function preview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const goal = form.goal.trim();
    if (!form.projectId || !goal) {
      setPreviewError('请选择项目并填写目标描述。');
      return;
    }
    setPreviewing(true);
    setPreviewError('');
    try {
      const result = await workbenchApi.previewPlan({
        tenant_id: currentUser.tenant_id,
        project_id: form.projectId,
        goal,
        deadline: form.deadline || null,
        budget: form.budget ? Number(form.budget) : null,
        constraints: form.constraints.trim() ? { notes: form.constraints.trim() } : {},
      });
      const nextVariants = cloneVariants(Array.isArray(result.variants) ? result.variants : []);
      if (nextVariants.length === 0) {
        setPreviewError('服务端没有返回可用方案，请调整目标后重试。');
        return;
      }
      setPlan(result);
      setOriginalVariants(cloneVariants(nextVariants));
      setVariants(nextVariants);
      setSelectedVariantKey(nextVariants[0].key);
      setConfirmed(false);
      setDispatchKey('');
      setDispatchError('');
      setDispatchConflict(false);
      setStep(2);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 403) {
        setPreviewError('无权为该项目生成或下发规划方案。');
      } else if (caught instanceof ApiError && caught.status === 422) {
        setPreviewError(`规划参数未通过服务端校验：${caught.message}`);
      } else {
        setPreviewError('方案生成失败，请检查网络或调整目标后重试。');
      }
    } finally {
      setPreviewing(false);
    }
  }

  function updateTask(
    variantKey: PlanVariantKey,
    taskKey: string,
    values: Partial<PlanningTask>,
  ) {
    setVariants((current) => current.map((variant) => (
      variant.key === variantKey
        ? {
            ...variant,
            tasks: variant.tasks.map((task) => {
              if (task.key !== taskKey) return task;
              const originalTask = originalVariants
                .find((candidate) => candidate.key === variantKey)
                ?.tasks.find((candidate) => candidate.key === taskKey);
              if (
                Object.prototype.hasOwnProperty.call(values, 'assignee_user_id')
                && values.assignee_user_id !== task.assignee_user_id
              ) {
                if (originalTask && values.assignee_user_id === originalTask.assignee_user_id) {
                  return {
                    ...task,
                    ...values,
                    assignment: { ...originalTask.assignment },
                    unassigned_reason: originalTask.unassigned_reason,
                  };
                }
                return {
                  ...task,
                  ...values,
                  assignment: {
                    provenance: 'manual',
                    manual_assignment_kind: originalTask?.assignee_user_id
                      ? 'reassigned'
                      : 'assigned',
                    previous_assignee_user_id: originalTask?.assignee_user_id || null,
                  },
                  unassigned_reason: values.assignee_user_id
                    ? null
                    : '负责人已由管理者人工取消指派',
                };
              }
              return { ...task, ...values };
            }),
          }
        : variant
    )));
  }

  function enterConfirmation() {
    setDispatchKey(createDispatchKey());
    setConfirmed(false);
    setDispatchError('');
    setDispatchConflict(false);
    setStep(3);
  }

  function returnToEditing() {
    setDispatchKey('');
    setConfirmed(false);
    setDispatchError('');
    setDispatchConflict(false);
    setStep(2);
  }

  async function dispatch() {
    if (!plan || !selectedVariant || !confirmed || dispatching) return;
    const stableKey = dispatchKey || createDispatchKey();
    if (!dispatchKey) setDispatchKey(stableKey);
    setDispatching(true);
    setDispatchError('');
    setDispatchConflict(false);
    try {
      await workbenchApi.dispatchPlan(plan.id, {
        tenant_id: currentUser.tenant_id,
        variant_key: selectedVariant.key,
        idempotency_key: stableKey,
        tasks: dispatchTasks(selectedVariant),
      });
      navigate(`/enterprise/tasks?project_id=${encodeURIComponent(plan.project_id)}`);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setDispatchConflict(true);
        setDispatchError('方案状态已变化，可能已由其他页面下发。请前往任务中心核对。');
      } else if (caught instanceof ApiError && caught.status === 403) {
        setDispatchError('下发被拒绝：当前账号没有该项目的调度权限。');
      } else if (caught instanceof ApiError && caught.status === 422) {
        setDispatchError('编辑后的 WBS 未通过服务端校验，请返回调整负责人、日期或依赖。');
      } else {
        setDispatchError('下发失败，请确认网络后重试。');
      }
    } finally {
      setDispatching(false);
    }
  }

  return (
    <WorkbenchLayout
      title="AI 调度中心"
      description="AI 负责拆解、推荐与总结，真人员工承担任务与审核责任"
      currentUser={currentUser}
      onLogout={onLogout}
    >
      <WizardSteps current={step} />

      {loading ? (
        <div role="status" aria-label="规划上下文加载中" className="mt-[18px] space-y-[14px]">
          <Skeleton className="h-[86px] rounded-[16px] bg-[#e9edf4]" />
          <Skeleton className="h-[360px] rounded-[16px] bg-[#e9edf4]" />
        </div>
      ) : loadError ? (
        <PlanningState
          permissionDenied={loadError instanceof ApiError && loadError.status === 403}
          onRetry={() => setRefreshKey((value) => value + 1)}
        />
      ) : access && projects.length > 0 && plannableProjects.length === 0 ? (
        <section role="alert" className="mt-[18px] rounded-[16px] border border-[#f1d4d4] bg-white px-[24px] py-[40px] text-center">
          <CircleAlert className="mx-auto size-[28px] text-[#d20b0b]" aria-hidden="true" />
          <h2 className="mt-[12px] mb-0 text-[16px] font-semibold text-[#24262d]">无权使用 AI 调度中心</h2>
          <p className="mt-[6px] mb-0 text-[12px] text-[#757f9c]">只有全局管理者、受管部门负责人或项目所有者可以生成并下发方案。</p>
        </section>
      ) : plannableProjects.length === 0 ? (
        <section className="mt-[18px] rounded-[16px] border border-dashed border-[#ccd5e5] bg-white px-[24px] py-[50px] text-center">
          <Sparkles className="mx-auto size-[30px] text-[#9aa8bf]" aria-hidden="true" />
          <h2 className="mt-[12px] mb-0 text-[16px] font-semibold text-[#464c5e]">还没有可规划项目</h2>
          <p className="mt-[6px] mb-0 text-[12px] text-[#858b9c]">请先创建一个进行中的项目，再让 AI 提供拆解与人员匹配建议。</p>
          <Button asChild className="mt-[16px] h-[34px] rounded-[10px] bg-[#18181a] px-[16px] text-[12px] text-white hover:bg-[#303030]">
            <Link to="/enterprise/projects">前往项目中心</Link>
          </Button>
        </section>
      ) : step === 1 ? (
        <section className="mt-[18px] rounded-[16px] border border-[#edf0f5] bg-white p-[22px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
          <div className="flex items-start gap-[11px]">
            <span className="flex size-[36px] shrink-0 items-center justify-center rounded-[11px] bg-[#eef4ff] text-[#1a71ff]">
              <Sparkles className="size-[17px]" aria-hidden="true" />
            </span>
            <div>
              <h2 className="m-0 text-[16px] font-semibold text-[#24262d]">规划目标与约束</h2>
              <p className="mt-[5px] mb-0 text-[11px] leading-[18px] text-[#858b9c]">服务端会读取真实员工岗位、技能、容量和成本，生成三套可解释方案。</p>
            </div>
          </div>
          <form onSubmit={preview} className="mt-[20px] grid gap-[16px] md:grid-cols-2">
            <FormField label="项目" className="md:col-span-2">
              <select
                value={form.projectId}
                onChange={(event) => setForm((value) => ({ ...value, projectId: event.target.value }))}
                className="h-[36px] w-full rounded-[10px] border border-[#e3e7f1] bg-white px-[10px] text-[13px] text-[#464c5e] outline-none focus:border-[#18181a]"
              >
                {plannableProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
              </select>
            </FormField>
            <FormField label="目标描述" className="md:col-span-2">
              <Textarea
                value={form.goal}
                onChange={(event) => setForm((value) => ({ ...value, goal: event.target.value }))}
                className="min-h-[110px] rounded-[10px] border-[#e3e7f1] text-[13px]"
                placeholder="例如：在月底前完成新品发布，并确保客服与销售具备上线准备"
              />
            </FormField>
            <FormField label="截止日期">
              <Input type="date" value={form.deadline} onChange={(event) => setForm((value) => ({ ...value, deadline: event.target.value }))} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
            </FormField>
            <FormField label="预算">
              <Input type="number" min="0" step="0.01" value={form.budget} onChange={(event) => setForm((value) => ({ ...value, budget: event.target.value }))} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
            </FormField>
            <FormField label="补充约束" className="md:col-span-2">
              <Textarea value={form.constraints} onChange={(event) => setForm((value) => ({ ...value, constraints: event.target.value }))} className="min-h-[78px] rounded-[10px] border-[#e3e7f1] text-[13px]" placeholder="团队偏好、必须遵守的顺序、可用时间等" />
            </FormField>
            {previewing && <p role="status" aria-label="正在生成规划方案" className="m-0 text-[12px] text-[#1a71ff] md:col-span-2">AI 正在拆解目标并计算人员匹配、排期与风险…</p>}
            {previewError && <p role="alert" className="m-0 text-[12px] leading-[19px] text-[#d20b0b] md:col-span-2">{previewError}</p>}
            <div className="flex justify-end md:col-span-2">
              <Button type="submit" disabled={previewing} className="h-[36px] gap-[7px] rounded-[10px] bg-[#18181a] px-[18px] text-[12px] text-white hover:bg-[#303030]">
                <Sparkles className="size-[14px]" aria-hidden="true" />
                {previewing ? '正在生成方案…' : '生成三套方案'}
              </Button>
            </div>
          </form>
        </section>
      ) : step === 2 && plan ? (
        <div className="mt-[18px]">
          <div className="mb-[14px] flex flex-wrap items-center justify-between gap-[10px]">
            <div className="flex items-center gap-[8px]">
              <span className={`rounded-full px-[9px] py-[5px] text-[10px] font-medium ${plan.source === 'fallback' ? 'bg-[#fff4dd] text-[#a65f00]' : 'bg-[#e9f7ef] text-[#018434]'}`}>
                {plan.source === 'fallback' ? '内置规划引擎' : '模型规划建议'}
              </span>
              <span className="text-[11px] text-[#858b9c]">方案可编辑，AI 不承担任务责任</span>
            </div>
            <div className="flex gap-[8px]">
              <Button type="button" variant="outline" onClick={() => setStep(1)} className="h-[34px] gap-[5px] rounded-[10px] border-[#e3e7f1] px-[13px] text-[12px] text-[#596176]">
                <ArrowLeft className="size-[13px]" aria-hidden="true" />
                修改目标
              </Button>
              <Button type="button" onClick={enterConfirmation} className="h-[34px] gap-[5px] rounded-[10px] bg-[#18181a] px-[15px] text-[12px] text-white hover:bg-[#303030]">
                进入确认
                <ArrowRight className="size-[13px]" aria-hidden="true" />
              </Button>
            </div>
          </div>
          <PlanComparison
            variants={variants}
            employees={employees}
            selectedVariantKey={selectedVariantKey}
            editedVariantKeys={editedVariantKeys}
            onSelectVariant={setSelectedVariantKey}
            onUpdateTask={updateTask}
          />
        </div>
      ) : step === 3 && plan && selectedVariant ? (
        <section className="mt-[18px] rounded-[16px] border border-[#edf0f5] bg-white p-[22px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
          <h2 className="m-0 text-[17px] font-semibold text-[#24262d]">确认下发方案</h2>
          <p className="mt-[6px] mb-0 text-[12px] leading-[19px] text-[#757f9c]">下发后将由服务端一次性创建任务与依赖。AI 建议不会替代真人负责人与审核人。</p>
          {selectedVariantEdited && (
            <p className="mt-[10px] mb-0 rounded-[10px] bg-[#fff4dd] px-[12px] py-[9px] text-[11px] leading-[18px] text-[#a65f00]">
              <span className="font-semibold">已修改 WBS</span> · 以下为人工编辑后的 WBS；对比指标仍为 AI 原始方案估算，未随编辑重新计算。
            </p>
          )}

          <div className="mt-[18px] grid gap-[12px] sm:grid-cols-2 lg:grid-cols-4">
            <Summary label="选择方案" value={selectedVariant.name} />
            <Summary label="任务数量" value={`${selectedVariant.tasks.length} 项`} />
            <Summary label={selectedVariantEdited ? 'AI 原始预计完成' : '预计完成'} value={String(selectedVariant.metrics.finish_date || '待计算')} />
            <Summary label={selectedVariantEdited ? 'AI 原始预计成本' : '预计成本'} value={formatCurrency(selectedVariant.metrics.cost)} />
          </div>

          <p className="mt-[16px] mb-0 rounded-[11px] bg-[#f7f9fc] px-[14px] py-[11px] text-[12px] font-medium text-[#464c5e]">
            真人负责人 {new Set(selectedVariant.tasks.map((task) => task.assignee_user_id).filter(Boolean)).size} 人 · 待人工指派 {selectedVariant.tasks.filter((task) => !task.assignee_user_id).length} 项
          </p>

          <div className="mt-[14px] space-y-[8px]">
            {selectedVariant.tasks.map((task) => {
              const assignee = employees.find((employee) => employee.user_id === task.assignee_user_id);
              const assigneeLabel = assignee?.display_name
                || assignee?.username
                || (task.assignee_user_id
                  ? '已指派（员工目录信息受限）'
                  : '待人工指派');
              return (
                <div key={task.key} className="flex flex-wrap items-center justify-between gap-[8px] rounded-[10px] border border-[#edf0f5] px-[12px] py-[10px] text-[11px]">
                  <span className="font-medium text-[#464c5e]">{task.title}</span>
                  <span className={task.assignee_user_id ? 'text-[#596176]' : 'text-[#a65f00]'}>
                    <span>{assigneeLabel}</span> · {task.due_date || '日期待定'}
                  </span>
                </div>
              );
            })}
          </div>

          <label className="mt-[18px] flex items-start gap-[9px] rounded-[12px] border border-[#dfe6f2] bg-[#f8faff] px-[14px] py-[12px] text-[12px] leading-[19px] text-[#464c5e]">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} className="mt-[2px] size-[14px] accent-[#1a71ff]" />
            <span>我已确认由真人员工承担任务责任</span>
          </label>

          {dispatchError && (
            <p role="alert" className={`mt-[12px] mb-0 rounded-[10px] px-[12px] py-[9px] text-[12px] ${dispatchConflict ? 'bg-[#fff4dd] text-[#a65f00]' : 'bg-[#fce7e7] text-[#d20b0b]'}`}>
              {dispatchError}
            </p>
          )}

          <div className="mt-[18px] flex flex-wrap justify-end gap-[8px]">
            <Button type="button" variant="outline" disabled={dispatching} onClick={returnToEditing} className="h-[34px] rounded-[10px] border-[#e3e7f1] px-[14px] text-[12px] text-[#596176]">返回调整</Button>
            {dispatchError && !dispatchConflict ? (
              <Button type="button" disabled={dispatching} onClick={dispatch} className="h-[34px] rounded-[10px] bg-[#18181a] px-[16px] text-[12px] text-white hover:bg-[#303030]">
                {dispatching ? '下发中…' : '重试下发'}
              </Button>
            ) : (
              <Button type="button" disabled={!confirmed || dispatching || dispatchConflict} onClick={dispatch} className="h-[34px] rounded-[10px] bg-[#18181a] px-[16px] text-[12px] text-white hover:bg-[#303030]">
                {dispatching ? '下发中…' : '确认并下发'}
              </Button>
            )}
          </div>
        </section>
      ) : null}
    </WorkbenchLayout>
  );
}

function WizardSteps({ current }: { current: 1 | 2 | 3 }) {
  return (
    <ol aria-label="规划步骤" className="grid grid-cols-3 overflow-hidden rounded-[14px] border border-[#e6eaf1] bg-white p-[5px]">
      {['目标与约束', '方案比较', '确认下发'].map((label, index) => {
        const step = (index + 1) as 1 | 2 | 3;
        return (
          <li key={label} aria-current={current === step ? 'step' : undefined} className={`flex min-w-0 items-center justify-center gap-[7px] rounded-[10px] px-[8px] py-[9px] text-[11px] ${current === step ? 'bg-[#18181a] font-medium text-white' : current > step ? 'text-[#1a71ff]' : 'text-[#9aa1b3]'}`}>
            <span className={`flex size-[18px] shrink-0 items-center justify-center rounded-full text-[9px] ${current === step ? 'bg-white/15' : 'bg-[#f1f3f7]'}`}>{step}</span>
            <span className="truncate">{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function PlanningState({ permissionDenied, onRetry }: { permissionDenied: boolean; onRetry: () => void }) {
  return (
    <section role="alert" className="mt-[18px] rounded-[16px] border border-[#f1d4d4] bg-white px-[24px] py-[40px] text-center">
      <CircleAlert className="mx-auto size-[28px] text-[#d20b0b]" aria-hidden="true" />
      <h2 className="mt-[12px] mb-0 text-[16px] font-semibold text-[#24262d]">{permissionDenied ? '无权使用 AI 调度中心' : '规划上下文加载失败'}</h2>
      <p className="mt-[6px] mb-0 text-[12px] text-[#757f9c]">{permissionDenied ? '当前账号无法读取调度所需的项目或真人员工范围。' : '未能读取项目、权限或员工数据，请稍后重试。'}</p>
      <Button type="button" onClick={onRetry} className="mt-[16px] h-[34px] rounded-[10px] bg-[#18181a] px-[18px] text-[12px] text-white hover:bg-[#303030]">重试</Button>
    </section>
  );
}

function FormField({ label, className, children }: { label: string; className?: string; children: React.ReactNode }) {
  return (
    <label className={`grid gap-[7px] ${className || ''}`}>
      <span className="text-[12px] font-medium text-[#464c5e]">{label}</span>
      {children}
    </label>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[11px] border border-[#edf0f5] bg-[#fbfcfe] px-[13px] py-[11px]">
      <p className="m-0 text-[10px] text-[#9aa1b3]">{label}</p>
      <p className="mt-[5px] mb-0 text-[13px] font-semibold text-[#464c5e]">{value}</p>
    </div>
  );
}
