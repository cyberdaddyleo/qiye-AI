import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { CalendarDays, CircleAlert, FolderKanban, Plus } from 'lucide-react';
import { Link } from 'react-router-dom';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { notify } from '@/components/ui/app-toast';
import {
  DIALOG_CANCEL_BUTTON_CLASS,
  DIALOG_FOOTER_CLASS,
  DIALOG_PRIMARY_BUTTON_CLASS,
} from '@/lib/enterprise-ui';
import type { DepartmentRead, EmployeeRead, ProjectRead } from '@/types/workbench';

import WorkbenchLayout from './WorkbenchLayout';
import { workbenchApi } from './workbenchApi';
import { projectProgress } from './workbenchModel';

export type ProjectsPageProps = {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
};

const STATUS_LABEL: Record<ProjectRead['status'], string> = {
  active: '进行中',
  on_hold: '已暂停',
  completed: '已完成',
  archived: '已归档',
};

const HEALTH_PRESENTATION: Record<ProjectRead['health'], { label: string; className: string }> = {
  on_track: { label: '进展正常', className: 'bg-[#e9f7ef] text-[#018434]' },
  at_risk: { label: '存在风险', className: 'bg-[#fff4dd] text-[#a65f00]' },
  off_track: { label: '已经偏离', className: 'bg-[#fce7e7] text-[#d20b0b]' },
};

type ProjectForm = {
  name: string;
  objective: string;
  description: string;
  departmentId: string;
  startDate: string;
  dueDate: string;
  budget: string;
};

type ProjectLoadFailure = {
  source: 'projects' | 'departments' | 'employees';
  reason: unknown;
};

const EMPTY_FORM: ProjectForm = {
  name: '',
  objective: '',
  description: '',
  departmentId: '',
  startDate: '',
  dueDate: '',
  budget: '',
};

export default function ProjectsPage({ currentUser, onLogout }: ProjectsPageProps) {
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [departments, setDepartments] = useState<DepartmentRead[]>([]);
  const [employees, setEmployees] = useState<EmployeeRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailure, setLoadFailure] = useState<ProjectLoadFailure | null>(null);
  const [memberDirectoriesRestricted, setMemberDirectoriesRestricted] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState<ProjectForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadFailure(null);
    setMemberDirectoriesRestricted(false);
    void Promise.allSettled([
      workbenchApi.listProjects(currentUser.tenant_id),
      workbenchApi.listDepartments(currentUser.tenant_id),
      workbenchApi.listEmployees(currentUser.tenant_id),
    ]).then(([projectResult, departmentResult, employeeResult]) => {
      if (!active) return;
      setProjects(
        projectResult.status === 'fulfilled' && Array.isArray(projectResult.value)
          ? projectResult.value
          : [],
      );
      setDepartments(
        departmentResult.status === 'fulfilled' && Array.isArray(departmentResult.value)
          ? departmentResult.value
          : [],
      );
      setEmployees(
        employeeResult.status === 'fulfilled' && Array.isArray(employeeResult.value)
          ? employeeResult.value
          : [],
      );
      const expectedMemberDirectoryDenials = currentUser.role === 'member'
        && departmentResult.status === 'rejected'
        && departmentResult.reason instanceof ApiError
        && departmentResult.reason.status === 403
        && employeeResult.status === 'rejected'
        && employeeResult.reason instanceof ApiError
        && employeeResult.reason.status === 403;
      if (projectResult.status === 'rejected') {
        setLoadFailure({ source: 'projects', reason: projectResult.reason });
      } else if (expectedMemberDirectoryDenials) {
        setMemberDirectoriesRestricted(true);
      } else if (departmentResult.status === 'rejected') {
        setLoadFailure({ source: 'departments', reason: departmentResult.reason });
      } else if (employeeResult.status === 'rejected') {
        setLoadFailure({ source: 'employees', reason: employeeResult.reason });
      }
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [currentUser.role, currentUser.tenant_id, refreshKey]);

  const self = employees.find((employee) => employee.user_id === currentUser.id);
  const canCreate = currentUser.role === 'admin'
    || self?.business_role === 'ceo'
    || self?.business_role === 'manager';
  const activeDepartments = useMemo(
    () => departments.filter((department) => department.status === 'active'),
    [departments],
  );
  const departmentById = useMemo(
    () => new Map(departments.map((department) => [department.id, department])),
    [departments],
  );

  function openCreateDialog() {
    setForm({ ...EMPTY_FORM, departmentId: activeDepartments[0]?.id || '' });
    setSaveError('');
    setDialogOpen(true);
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = form.name.trim();
    const objective = form.objective.trim();
    if (!name || !objective || !form.departmentId) {
      setSaveError('请填写项目名称、目标和所属部门。');
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      const created = await workbenchApi.createProject({
        tenant_id: currentUser.tenant_id,
        name,
        objective,
        description: form.description.trim() || null,
        owner_user_id: currentUser.id,
        department_id: form.departmentId,
        start_date: form.startDate || null,
        due_date: form.dueDate || null,
        budget: form.budget ? Number(form.budget) : null,
      });
      setProjects((rows) => [created, ...rows]);
      setDialogOpen(false);
      notify.success('项目创建成功');
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '项目创建失败';
      setSaveError(message);
      notify.error(message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <WorkbenchLayout
      title="项目中心"
      description="创建项目并跟踪目标、进度与健康状态"
      currentUser={currentUser}
      onLogout={onLogout}
      actions={!loading && !loadFailure && canCreate ? (
        <Button type="button" onClick={openCreateDialog} className="h-[34px] gap-[6px] rounded-[10px] bg-[#18181a] px-[14px] text-[12px] text-white hover:bg-[#303030]">
          <Plus className="size-[14px]" aria-hidden="true" />
          新建项目
        </Button>
      ) : undefined}
    >
      {loading ? (
        <div role="status" aria-label="项目加载中" className="grid grid-cols-1 gap-[16px] lg:grid-cols-2">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-[250px] rounded-[16px] bg-[#e9edf4]" />
          ))}
        </div>
      ) : loadFailure ? (
        <ProjectError
          failure={loadFailure}
          onRetry={() => setRefreshKey((value) => value + 1)}
        />
      ) : projects.length === 0 ? (
        <section className="rounded-[16px] border border-dashed border-[#ccd5e5] bg-white px-[24px] py-[52px] text-center">
          <FolderKanban className="mx-auto size-[30px] text-[#9aa8bf]" aria-hidden="true" />
          <h2 className="mt-[12px] mb-0 text-[15px] font-semibold text-[#464c5e]">还没有可见项目</h2>
          <p className="mt-[6px] mb-0 text-[12px] text-[#858b9c]">
            {canCreate ? '创建首个项目，把目标交给真人团队推进。' : '参与项目后会在这里显示。'}
          </p>
          {canCreate && (
            <Button type="button" onClick={openCreateDialog} className="mt-[18px] h-[34px] rounded-[10px] bg-[#18181a] px-[16px] text-[12px] text-white hover:bg-[#303030]">
              新建项目
            </Button>
          )}
        </section>
      ) : (
        <div className="grid grid-cols-1 gap-[16px] lg:grid-cols-2">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              departmentName={departmentById.get(project.department_id || '')?.name
                || (memberDirectoriesRestricted && project.department_id ? '部门信息受限' : undefined)}
            />
          ))}
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={(open) => !saving && setDialogOpen(open)}>
        <DialogContent className="w-[calc(100%-32px)] gap-0 overflow-hidden rounded-[16px] p-0 sm:max-w-[560px]">
          <div className="border-b border-[#edf0f5] px-[24px] py-[18px]">
            <DialogTitle className="text-[16px] font-semibold text-[#24262d]">新建项目</DialogTitle>
            <DialogDescription className="mt-[6px] text-[12px] leading-[19px] text-[#858b9c]">
              项目由真人负责人承担，AI 仅在后续规划中提供拆解与匹配建议。
            </DialogDescription>
          </div>
          <form onSubmit={createProject}>
            <div className="grid max-h-[calc(100dvh-190px)] gap-[16px] overflow-y-auto px-[24px] py-[20px] sm:grid-cols-2">
              <FormField label="项目名称" className="sm:col-span-2">
                <Input value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
              </FormField>
              <FormField label="项目目标" className="sm:col-span-2">
                <Textarea value={form.objective} onChange={(event) => setForm((value) => ({ ...value, objective: event.target.value }))} className="min-h-[82px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
              </FormField>
              <FormField label="项目说明" className="sm:col-span-2">
                <Textarea value={form.description} onChange={(event) => setForm((value) => ({ ...value, description: event.target.value }))} className="min-h-[70px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
              </FormField>
              <FormField label="所属部门">
                <select value={form.departmentId} onChange={(event) => setForm((value) => ({ ...value, departmentId: event.target.value }))} className="h-[36px] w-full rounded-[10px] border border-[#e3e7f1] bg-white px-[10px] text-[13px] text-[#464c5e] outline-none focus:border-[#18181a]">
                  <option value="">请选择部门</option>
                  {activeDepartments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
                </select>
              </FormField>
              <FormField label="预算">
                <Input type="number" min="0" step="0.01" value={form.budget} onChange={(event) => setForm((value) => ({ ...value, budget: event.target.value }))} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
              </FormField>
              <FormField label="开始日期">
                <Input type="date" value={form.startDate} onChange={(event) => setForm((value) => ({ ...value, startDate: event.target.value }))} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
              </FormField>
              <FormField label="截止日期">
                <Input type="date" value={form.dueDate} onChange={(event) => setForm((value) => ({ ...value, dueDate: event.target.value }))} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" />
              </FormField>
              {saveError && <p role="alert" className="m-0 text-[12px] text-[#d20b0b] sm:col-span-2">{saveError}</p>}
            </div>
            <DialogFooter className={`${DIALOG_FOOTER_CLASS} border-t border-[#edf0f5]`}>
              <Button type="button" variant="outline" disabled={saving} onClick={() => setDialogOpen(false)} className={DIALOG_CANCEL_BUTTON_CLASS}>取消</Button>
              <Button type="submit" disabled={saving} className={DIALOG_PRIMARY_BUTTON_CLASS}>{saving ? '创建中…' : '创建项目'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </WorkbenchLayout>
  );
}

function ProjectError({ failure, onRetry }: { failure: ProjectLoadFailure; onRetry: () => void }) {
  const permissionDenied = failure.reason instanceof ApiError && failure.reason.status === 403;
  const presentation = {
    projects: permissionDenied
      ? {
          title: '无权查看项目中心',
          detail: '当前账号没有项目中心的访问权限。',
        }
      : {
          title: '项目加载失败',
          detail: '未能读取项目，请检查网络后重试。',
        },
    departments: permissionDenied
      ? {
          title: '无权读取项目部门信息',
          detail: '当前账号无法读取项目所属部门，请联系管理员或重试。',
        }
      : {
          title: '项目部门信息加载失败',
          detail: '未能读取项目所属部门，为避免展示错误信息，请重试。',
        },
    employees: permissionDenied
      ? {
          title: '无权读取项目身份信息',
          detail: '当前账号无法读取项目身份与创建权限，请联系管理员或重试。',
        }
      : {
          title: '项目身份信息加载失败',
          detail: '未能读取员工身份与创建权限，为避免误判权限，请重试。',
        },
  }[failure.source];

  return (
    <section role="alert" className="rounded-[16px] border border-[#f1d4d4] bg-white px-[24px] py-[36px] text-center">
      <CircleAlert className="mx-auto size-[28px] text-[#d20b0b]" aria-hidden="true" />
      <h2 className="mt-[12px] mb-0 text-[16px] font-semibold text-[#24262d]">
        {presentation.title}
      </h2>
      <p className="mt-[6px] mb-0 text-[12px] text-[#757f9c]">
        {presentation.detail}
      </p>
      <Button type="button" onClick={onRetry} className="mt-[16px] h-[34px] rounded-[10px] bg-[#18181a] px-[18px] text-[12px] text-white hover:bg-[#303030]">重试</Button>
    </section>
  );
}

function ProjectCard({ project, departmentName }: { project: ProjectRead; departmentName?: string }) {
  const progress = projectProgress(project);
  const health = HEALTH_PRESENTATION[project.health];
  return (
    <article aria-label={project.name} className="flex min-w-0 flex-col rounded-[16px] border border-[#edf0f5] bg-white p-[20px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
      <div className="flex items-start justify-between gap-[14px]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-[7px]">
            <h2 className="m-0 truncate text-[16px] font-semibold text-[#24262d]">{project.name}</h2>
            <span className="rounded-full bg-[#f2f3f7] px-[8px] py-[3px] text-[10px] text-[#596176]">{STATUS_LABEL[project.status]}</span>
            <span className={`rounded-full px-[8px] py-[3px] text-[10px] font-medium ${health.className}`}>{health.label}</span>
          </div>
          <p className="mt-[8px] mb-0 line-clamp-2 text-[12px] leading-[19px] text-[#596176]">{project.objective}</p>
        </div>
        <span className="flex size-[38px] shrink-0 items-center justify-center rounded-[11px] bg-[#eef4ff] text-[#1a71ff]">
          <FolderKanban className="size-[17px]" aria-hidden="true" />
        </span>
      </div>

      <dl className="mt-[18px] grid grid-cols-2 gap-x-[14px] gap-y-[10px] border-y border-[#f0f2f6] py-[14px] text-[11px]">
        <div><dt className="text-[#9aa1b3]">所属部门</dt><dd className="mt-[3px] mb-0 text-[#596176]">{departmentName || '未设置'}</dd></div>
        <div><dt className="text-[#9aa1b3]">任务完成</dt><dd className="mt-[3px] mb-0 text-[#596176]">{project.task_done} / {project.task_total}</dd></div>
        <div className="col-span-2 flex items-center gap-[6px]"><CalendarDays className="size-[12px] text-[#9aa1b3]" aria-hidden="true" /><dt className="sr-only">周期</dt><dd className="m-0 text-[#596176]">{project.start_date || '未定'} 至 {project.due_date || '未定'}</dd></div>
      </dl>

      <div className="mt-[16px]">
        <div className="flex items-center justify-between text-[11px]"><span className="text-[#858b9c]">任务进度</span><span className="font-semibold text-[#464c5e]">{progress}%</span></div>
        <div className="mt-[7px] h-[7px] overflow-hidden rounded-full bg-[#edf0f5]" role="progressbar" aria-label={`${project.name}进度`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
          <span className="block h-full rounded-full bg-[#1a71ff]" style={{ width: `${progress}%` }} />
        </div>
      </div>

      <div className="mt-[18px] flex flex-wrap gap-[8px]">
        <Button asChild variant="outline" className="h-[32px] rounded-[9px] border-[#e3e7f1] px-[12px] text-[12px] font-normal text-[#596176] hover:bg-[#f6f7f9]">
          <Link to={`/enterprise/tasks?project_id=${encodeURIComponent(project.id)}`}>查看任务</Link>
        </Button>
        <Button asChild className="h-[32px] rounded-[9px] bg-[#18181a] px-[12px] text-[12px] font-normal text-white hover:bg-[#303030]">
          <Link to={`/enterprise/planning?project_id=${encodeURIComponent(project.id)}`}>AI 规划</Link>
        </Button>
      </div>
    </article>
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
