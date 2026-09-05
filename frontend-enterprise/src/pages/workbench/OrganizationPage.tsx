import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { CircleAlert, FileSpreadsheet, Plus, Search, UsersRound } from 'lucide-react';

import { ApiError } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import { DataTable, type DataTableColumn } from '@/components/DataTable';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { notify } from '@/components/ui/app-toast';
import {
  DIALOG_CANCEL_BUTTON_CLASS,
  DIALOG_FOOTER_CLASS,
  DIALOG_PRIMARY_BUTTON_CLASS,
} from '@/lib/enterprise-ui';
import type { AgentProfileRead } from '@/types';
import type {
  BusinessRole,
  DepartmentRead,
  EmployeeImportResult,
  EmployeeRead,
  EmployeeStatus,
  EmployeeUpdateRequest,
} from '@/types/workbench';

import WorkbenchLayout from './WorkbenchLayout';
import { workbenchApi } from './workbenchApi';
import EmployeeBadge from './components/EmployeeBadge';
import WorkloadBar from './components/WorkloadBar';

export type OrganizationPageProps = {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
  assistants?: AgentProfileRead[];
};

const ROLE_LABEL: Record<BusinessRole, string> = {
  admin: '管理员',
  ceo: 'CEO',
  manager: '部门负责人',
  member: '普通员工',
};

type EmployeeForm = {
  employeeNo: string;
  departmentId: string;
  jobTitle: string;
  businessRole: BusinessRole;
  level: string;
  skills: string;
  capacityPercent: string;
  dailyCost: string;
  managerUserId: string;
  assistantAgentId: string;
  status: EmployeeStatus;
};

function employeeName(employee: EmployeeRead): string {
  return employee.display_name || employee.username;
}

function employeeForm(employee: EmployeeRead): EmployeeForm {
  return {
    employeeNo: employee.employee_no || '',
    departmentId: employee.department_id || '',
    jobTitle: employee.job_title || '',
    businessRole: employee.business_role,
    level: employee.level || '',
    skills: employee.skills.join('，'),
    capacityPercent: String(employee.capacity_percent),
    dailyCost: employee.daily_cost == null ? '' : String(employee.daily_cost),
    managerUserId: employee.manager_user_id || '',
    assistantAgentId: employee.assistant_agent_id || '',
    status: employee.status,
  };
}

function currency(value: number | null): string {
  if (value == null) return '未设置';
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)} / 日`;
}

export default function OrganizationPage({
  currentUser,
  onLogout,
  assistants = [],
}: OrganizationPageProps) {
  const [departments, setDepartments] = useState<DepartmentRead[]>([]);
  const [employees, setEmployees] = useState<EmployeeRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedDepartment, setSelectedDepartment] = useState('all');
  const [search, setSearch] = useState('');
  const [departmentDialogOpen, setDepartmentDialogOpen] = useState(false);
  const [departmentName, setDepartmentName] = useState('');
  const [departmentCode, setDepartmentCode] = useState('');
  const [departmentSaving, setDepartmentSaving] = useState(false);
  const [departmentError, setDepartmentError] = useState('');
  const [editingEmployee, setEditingEmployee] = useState<EmployeeRead | null>(null);
  const [editForm, setEditForm] = useState<EmployeeForm | null>(null);
  const [employeeSaving, setEmployeeSaving] = useState(false);
  const [employeeError, setEmployeeError] = useState('');
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importError, setImportError] = useState('');
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<EmployeeImportResult | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    void Promise.all([
      workbenchApi.listDepartments(currentUser.tenant_id),
      workbenchApi.listEmployees(currentUser.tenant_id),
    ]).then(([departmentRows, employeeRows]) => {
      if (!active) return;
      setDepartments(Array.isArray(departmentRows) ? departmentRows : []);
      setEmployees(Array.isArray(employeeRows) ? employeeRows : []);
      setLoading(false);
    }).catch((caught) => {
      if (!active) return;
      setError(caught);
      setDepartments([]);
      setEmployees([]);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [currentUser.tenant_id, refreshKey]);

  const self = employees.find((employee) => employee.user_id === currentUser.id);
  const canManageAll = currentUser.role === 'admin' || self?.business_role === 'ceo';
  const canEditEmployees = canManageAll || self?.business_role === 'manager';
  const canShowMutations = !loading && !error;
  const activeDepartments = useMemo(
    () => departments.filter((department) => department.status === 'active'),
    [departments],
  );
  const departmentById = useMemo(
    () => new Map(departments.map((department) => [department.id, department])),
    [departments],
  );
  const employeeByUserId = useMemo(
    () => new Map(employees.map((employee) => [employee.user_id, employee])),
    [employees],
  );
  const visibleAssistants = useMemo(
    () => assistants.filter((assistant) => (
      assistant.tenant_id === currentUser.tenant_id
      && assistant.status === 'active'
      && !assistant.is_overall
    )),
    [assistants, currentUser.tenant_id],
  );
  const assistantById = useMemo(
    () => new Map(assistants.map((assistant) => [assistant.id, assistant])),
    [assistants],
  );
  const filteredEmployees = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return employees.filter((employee) => {
      if (selectedDepartment !== 'all' && employee.department_id !== selectedDepartment) return false;
      if (!needle) return true;
      return [
        employee.display_name,
        employee.username,
        employee.employee_no,
        employee.job_title,
        employee.level,
        ...employee.skills,
      ].some((value) => value?.toLocaleLowerCase().includes(needle));
    });
  }, [employees, search, selectedDepartment]);

  function openDepartmentDialog() {
    setDepartmentName('');
    setDepartmentCode('');
    setDepartmentError('');
    setDepartmentDialogOpen(true);
  }

  async function createDepartment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = departmentName.trim();
    const code = departmentCode.trim();
    if (!name || !code) {
      setDepartmentError('请填写部门名称和部门编码。');
      return;
    }
    setDepartmentSaving(true);
    setDepartmentError('');
    try {
      const created = await workbenchApi.createDepartment({
        tenant_id: currentUser.tenant_id,
        name,
        code,
      });
      setDepartments((rows) => [...rows, created]);
      setDepartmentDialogOpen(false);
      notify.success('部门创建成功');
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '部门创建失败';
      setDepartmentError(message);
      notify.error(message);
    } finally {
      setDepartmentSaving(false);
    }
  }

  function openEmployeeEditor(employee: EmployeeRead) {
    setEditingEmployee(employee);
    setEditForm(employeeForm(employee));
    setEmployeeError('');
  }

  async function saveEmployee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editingEmployee || !editForm) return;
    const capacity = Number(editForm.capacityPercent);
    if (!Number.isFinite(capacity) || capacity < 0 || capacity > 100) {
      setEmployeeError('可用率必须在 0 到 100 之间。');
      return;
    }
    const request: EmployeeUpdateRequest = {
      tenant_id: currentUser.tenant_id,
      employee_no: editForm.employeeNo.trim() || null,
      department_id: editForm.departmentId || null,
      job_title: editForm.jobTitle.trim() || null,
      business_role: editForm.businessRole,
      level: editForm.level.trim() || null,
      skills: editForm.skills.split(/[，,]/).map((skill) => skill.trim()).filter(Boolean),
      capacity_percent: capacity,
      daily_cost: editForm.dailyCost ? Number(editForm.dailyCost) : null,
      manager_user_id: editForm.managerUserId || null,
      assistant_agent_id: editForm.assistantAgentId || null,
      status: editForm.status,
    };
    setEmployeeSaving(true);
    setEmployeeError('');
    try {
      const updated = await workbenchApi.updateEmployee(editingEmployee.id, request);
      setEmployees((rows) => rows.map((employee) => employee.id === updated.id ? updated : employee));
      setEditingEmployee(null);
      setEditForm(null);
      notify.success('员工档案已更新');
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '员工档案更新失败';
      setEmployeeError(message);
      notify.error(message);
    } finally {
      setEmployeeSaving(false);
    }
  }

  function openImportDialog() {
    setImportFile(null);
    setImportError('');
    setImportResult(null);
    setImportOpen(true);
  }

  function chooseImportFile(file: File | undefined) {
    setImportResult(null);
    if (!file) {
      setImportFile(null);
      setImportError('');
      return;
    }
    if (!/\.(csv|xlsx)$/i.test(file.name)) {
      setImportFile(null);
      setImportError('仅支持 .csv 或 .xlsx 文件。');
      return;
    }
    setImportFile(file);
    setImportError('');
  }

  async function importEmployees() {
    if (!importFile) return;
    setImporting(true);
    setImportError('');
    try {
      const result = await workbenchApi.importEmployees(importFile, currentUser.tenant_id);
      try {
        const employeeRows = await workbenchApi.listEmployees(currentUser.tenant_id);
        setEmployees(Array.isArray(employeeRows) ? employeeRows : []);
      } catch {
        setImportError('导入已完成，但员工列表刷新失败，请关闭导入结果后重试页面。');
      }
      setImportResult(result);
      notify.success(`员工导入完成：新增 ${result.created}，更新 ${result.updated}`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '员工导入失败';
      setImportError(message);
      notify.error(message);
    } finally {
      setImporting(false);
    }
  }

  const columns: DataTableColumn<EmployeeRead>[] = [
    {
      key: 'employee',
      title: '真人员工',
      width: 190,
      render: (employee) => (
        <EmployeeBadge employee={employee} subtitle={employee.employee_no || '未设置工号'} />
      ),
    },
    {
      key: 'role',
      title: '岗位与角色',
      width: 150,
      render: (employee) => (
        <span className="block min-w-0">
          <span className="block truncate text-[12px] font-medium text-[#464c5e]">{employee.job_title || '未设置岗位'}</span>
          <span className="mt-[3px] block text-[11px] text-[#9aa1b3]">{ROLE_LABEL[employee.business_role]} · {employee.level || '未定级'}</span>
        </span>
      ),
    },
    {
      key: 'department',
      title: '部门',
      width: 110,
      render: (employee) => departmentById.get(employee.department_id || '')?.name || '未分配',
    },
    {
      key: 'capacity',
      title: '可用率',
      width: 150,
      render: (employee) => <WorkloadBar value={employee.capacity_percent} compact />,
    },
    {
      key: 'skills',
      title: '技能',
      width: 190,
      render: (employee) => employee.skills.length > 0 ? (
        <span className="flex flex-wrap gap-[4px]">
          {employee.skills.slice(0, 3).map((skill) => (
            <span key={skill} className="rounded-full bg-[#f2f5fa] px-[7px] py-[3px] text-[10px] text-[#596176]">{skill}</span>
          ))}
        </span>
      ) : '未设置',
    },
    {
      key: 'cost',
      title: '日成本',
      width: 110,
      render: (employee) => currency(employee.daily_cost),
    },
    {
      key: 'assistant',
      title: 'AI 助理关联',
      width: 160,
      render: (employee) => {
        const assistant = employee.assistant_agent_id
          ? assistantById.get(employee.assistant_agent_id)
          : undefined;
        return employee.assistant_agent_id
          ? `AI 助理：${assistant?.name || employee.assistant_agent_id}`
          : '未关联';
      },
    },
    ...(canEditEmployees ? [{
      key: 'action',
      title: '操作',
      width: 86,
      sticky: 'right' as const,
      render: (employee: EmployeeRead) => (
        <Button
          type="button"
          variant="outline"
          onClick={(event) => {
            event.stopPropagation();
            openEmployeeEditor(employee);
          }}
          aria-label={`编辑${employeeName(employee)}`}
          className="h-[29px] rounded-[8px] border-[#e3e7f1] px-[10px] text-[11px] font-normal text-[#596176] hover:bg-[#f6f7f9]"
        >
          编辑
        </Button>
      ),
    }] : []),
  ];

  const permissionDenied = error instanceof ApiError && error.status === 403;

  return (
    <WorkbenchLayout
      title="组织与权限"
      description="维护真人员工档案、部门容量与 AI 助理能力关联"
      currentUser={currentUser}
      onLogout={onLogout}
      actions={canManageAll && canShowMutations ? (
        <div className="flex items-center gap-[8px]">
          <Button type="button" variant="outline" onClick={openImportDialog} className="h-[34px] gap-[6px] rounded-[10px] border-[#dce2ec] bg-white px-[13px] text-[12px] font-normal text-[#596176] hover:bg-[#f6f7f9]">
            <FileSpreadsheet className="size-[14px]" aria-hidden="true" />导入员工
          </Button>
          <Button type="button" onClick={openDepartmentDialog} className="h-[34px] gap-[6px] rounded-[10px] bg-[#18181a] px-[13px] text-[12px] text-white hover:bg-[#303030]">
            <Plus className="size-[14px]" aria-hidden="true" />新建部门
          </Button>
        </div>
      ) : undefined}
    >
      {loading ? (
        <OrganizationLoading />
      ) : error ? (
        <OrganizationError permissionDenied={permissionDenied} onRetry={() => setRefreshKey((value) => value + 1)} />
      ) : (
        <div className="space-y-[16px]">
          {!canEditEmployees && (
            <section role="alert" className="rounded-[14px] border border-[#dbe7f8] bg-[#f6f9ff] px-[16px] py-[12px] text-[12px] leading-[19px] text-[#596176]">
              组织信息为只读。真人员工是工作责任主体，AI 助理仅提供经授权的能力支持。
            </section>
          )}

          <section className="rounded-[16px] border border-[#edf0f5] bg-white p-[16px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
            <div className="flex flex-col gap-[14px] xl:flex-row xl:items-center xl:justify-between">
              <div className="flex min-w-0 flex-wrap gap-[7px]" aria-label="部门筛选">
                <DepartmentChip active={selectedDepartment === 'all'} onClick={() => setSelectedDepartment('all')}>全部员工</DepartmentChip>
                {activeDepartments.map((department) => (
                  <DepartmentChip key={department.id} active={selectedDepartment === department.id} onClick={() => setSelectedDepartment(department.id)}>
                    {department.name}
                  </DepartmentChip>
                ))}
              </div>
              <label className="flex h-[34px] w-full max-w-[280px] items-center gap-[8px] rounded-[10px] border border-[#e3e7f1] bg-white px-[10px] focus-within:border-[#18181a]">
                <Search className="size-[14px] shrink-0 text-[#9aa1b3]" aria-hidden="true" />
                <span className="sr-only">搜索员工</span>
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名、岗位或技能" className="min-w-0 flex-1 bg-transparent text-[12px] text-[#464c5e] outline-none placeholder:text-[#b0b6c4]" />
              </label>
            </div>
          </section>

          <section className="min-w-0 rounded-[16px] border border-[#edf0f5] bg-white p-[16px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]">
            <div className="mb-[14px] flex items-center justify-between gap-[12px]">
              <div>
                <h2 className="m-0 text-[15px] font-semibold text-[#24262d]">真人员工</h2>
                <p className="mt-[4px] mb-0 text-[11px] text-[#858b9c]">共 {filteredEmployees.length} 人，任务归属与审计均记录真人账号</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <DataTable
                aria-label="员工组织列表"
                columns={columns}
                data={filteredEmployees}
                rowKey={(employee) => employee.id}
                emptyText={search || selectedDepartment !== 'all' ? '没有符合条件的员工' : '还没有员工档案'}
                className="min-w-[900px]"
              />
            </div>
          </section>
        </div>
      )}

      <Dialog open={departmentDialogOpen} onOpenChange={(open) => !departmentSaving && setDepartmentDialogOpen(open)}>
        <DialogContent className="w-[calc(100%-32px)] gap-0 overflow-hidden rounded-[16px] p-0 sm:max-w-[440px]">
          <div className="border-b border-[#edf0f5] px-[24px] py-[18px]">
            <DialogTitle className="text-[16px] font-semibold text-[#24262d]">新建部门</DialogTitle>
            <DialogDescription className="mt-[6px] text-[12px] text-[#858b9c]">创建后可把真人员工分配到该部门。</DialogDescription>
          </div>
          <form onSubmit={createDepartment}>
            <div className="grid gap-[16px] px-[24px] py-[20px]">
              <Field label="部门名称"><Input value={departmentName} onChange={(event) => setDepartmentName(event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="部门编码"><Input value={departmentCode} onChange={(event) => setDepartmentCode(event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              {departmentError && <p role="alert" className="m-0 text-[12px] text-[#d20b0b]">{departmentError}</p>}
            </div>
            <DialogFooter className={`${DIALOG_FOOTER_CLASS} border-t border-[#edf0f5]`}>
              <Button type="button" variant="outline" onClick={() => setDepartmentDialogOpen(false)} disabled={departmentSaving} className={DIALOG_CANCEL_BUTTON_CLASS}>取消</Button>
              <Button type="submit" disabled={departmentSaving} className={DIALOG_PRIMARY_BUTTON_CLASS}>{departmentSaving ? '创建中…' : '创建部门'}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <EmployeeEditor
        employee={editingEmployee}
        form={editForm}
        departments={activeDepartments}
        employees={employees}
        assistants={visibleAssistants}
        canAssignGlobalRole={canManageAll}
        saving={employeeSaving}
        error={employeeError}
        onChange={setEditForm}
        onClose={() => {
          if (!employeeSaving) {
            setEditingEmployee(null);
            setEditForm(null);
          }
        }}
        onSubmit={saveEmployee}
      />

      <ImportDialog
        open={importOpen}
        file={importFile}
        error={importError}
        result={importResult}
        importing={importing}
        onOpenChange={(open) => !importing && setImportOpen(open)}
        onFile={chooseImportFile}
        onImport={importEmployees}
      />
    </WorkbenchLayout>
  );
}

function OrganizationLoading() {
  return (
    <div role="status" aria-label="组织信息加载中" className="space-y-[16px]">
      <Skeleton className="h-[66px] rounded-[16px] bg-[#e9edf4]" />
      <Skeleton className="h-[360px] rounded-[16px] bg-[#e9edf4]" />
    </div>
  );
}

function OrganizationError({ permissionDenied, onRetry }: { permissionDenied: boolean; onRetry: () => void }) {
  return (
    <section role="alert" className="rounded-[16px] border border-[#dbe4f1] bg-white px-[24px] py-[36px] text-center">
      {permissionDenied ? <UsersRound className="mx-auto size-[29px] text-[#78869d]" aria-hidden="true" /> : <CircleAlert className="mx-auto size-[29px] text-[#d20b0b]" aria-hidden="true" />}
      <h2 className="mt-[12px] mb-0 text-[16px] font-semibold text-[#24262d]">
        {permissionDenied ? '组织信息为只读' : '组织信息加载失败'}
      </h2>
      <p className="mt-[6px] mb-0 text-[12px] leading-[20px] text-[#757f9c]">
        {permissionDenied
          ? '普通员工请在员工工作台查看自己的档案与任务；这里不提供组织修改操作。'
          : '未能读取部门和员工档案，请稍后重试。'}
      </p>
      {!permissionDenied && <Button type="button" onClick={onRetry} className="mt-[16px] h-[34px] rounded-[10px] bg-[#18181a] px-[18px] text-[12px] text-white hover:bg-[#303030]">重试</Button>}
    </section>
  );
}

function DepartmentChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick} className={`rounded-full border px-[12px] py-[6px] text-[11px] font-medium transition-colors ${active ? 'border-[#1a71ff] bg-[#edf4ff] text-[#1a71ff]' : 'border-[#e3e7f1] bg-white text-[#596176] hover:border-[#c6d0e0]'}`}>
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-[7px]">
      <span className="text-[12px] font-medium text-[#464c5e]">{label}</span>
      {children}
    </label>
  );
}

function EmployeeEditor({
  employee,
  form,
  departments,
  employees,
  assistants,
  canAssignGlobalRole,
  saving,
  error,
  onChange,
  onClose,
  onSubmit,
}: {
  employee: EmployeeRead | null;
  form: EmployeeForm | null;
  departments: DepartmentRead[];
  employees: EmployeeRead[];
  assistants: AgentProfileRead[];
  canAssignGlobalRole: boolean;
  saving: boolean;
  error: string;
  onChange: (form: EmployeeForm | null) => void;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const set = <K extends keyof EmployeeForm>(key: K, value: EmployeeForm[K]) => {
    if (form) onChange({ ...form, [key]: value });
  };
  return (
    <Sheet open={Boolean(employee && form)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 border-l border-[#e3e7f1] bg-white p-0 sm:max-w-[560px]">
        {employee && form && (
          <form onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
            <SheetHeader className="border-b border-[#edf0f5] px-[24px] py-[18px]">
              <SheetTitle className="text-[16px] font-semibold text-[#24262d]">编辑员工：{employeeName(employee)}</SheetTitle>
              <SheetDescription className="mt-[6px] text-[12px] leading-[19px] text-[#858b9c]">任务责任仍归真人账号；AI 助理绑定只表示可调用的能力关联。</SheetDescription>
            </SheetHeader>
            <div className="grid min-h-0 flex-1 gap-[16px] overflow-y-auto px-[24px] py-[20px] sm:grid-cols-2">
              <Field label="员工工号"><Input value={form.employeeNo} onChange={(event) => set('employeeNo', event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="岗位"><Input value={form.jobTitle} onChange={(event) => set('jobTitle', event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="所属部门"><NativeSelect value={form.departmentId} onChange={(value) => set('departmentId', value)}><option value="">未分配</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</NativeSelect></Field>
              <Field label="职级"><Input value={form.level} onChange={(event) => set('level', event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="业务角色"><NativeSelect value={form.businessRole} onChange={(value) => set('businessRole', value as BusinessRole)}><option value="member">普通员工</option><option value="manager">部门负责人</option>{canAssignGlobalRole && <option value="ceo">CEO</option>}{canAssignGlobalRole && <option value="admin">管理员</option>}</NativeSelect></Field>
              <Field label="状态"><NativeSelect value={form.status} onChange={(value) => set('status', value as EmployeeStatus)}><option value="active">在岗</option><option value="inactive">停用</option></NativeSelect></Field>
              <Field label="技能（逗号分隔）"><Input value={form.skills} onChange={(event) => set('skills', event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="可用率"><Input type="number" min="0" max="100" value={form.capacityPercent} onChange={(event) => set('capacityPercent', event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="日成本"><Input type="number" min="0" step="0.01" value={form.dailyCost} onChange={(event) => set('dailyCost', event.target.value)} className="h-[36px] rounded-[10px] border-[#e3e7f1] text-[13px]" /></Field>
              <Field label="直属经理"><NativeSelect value={form.managerUserId} onChange={(value) => set('managerUserId', value)}><option value="">未设置</option>{employees.filter((row) => row.user_id !== employee.user_id).map((row) => <option key={row.user_id} value={row.user_id}>{employeeName(row)}</option>)}</NativeSelect></Field>
              <div className="sm:col-span-2">
                <Field label="AI 助理关联"><NativeSelect value={form.assistantAgentId} onChange={(value) => set('assistantAgentId', value)}><option value="">不关联</option>{assistants.map((assistant) => <option key={assistant.id} value={assistant.id}>{assistant.name}</option>)}</NativeSelect></Field>
                <p className="mt-[6px] mb-0 text-[11px] leading-[17px] text-[#858b9c]">AI 助理不会成为任务负责人，也不会继承该员工的业务权限。</p>
              </div>
              {error && <p role="alert" className="m-0 text-[12px] text-[#d20b0b] sm:col-span-2">{error}</p>}
            </div>
            <SheetFooter className="flex-row justify-end border-t border-[#edf0f5] px-[24px] py-[12px]">
              <Button type="button" variant="outline" onClick={onClose} disabled={saving} className={DIALOG_CANCEL_BUTTON_CLASS}>取消</Button>
              <Button type="submit" disabled={saving} className={DIALOG_PRIMARY_BUTTON_CLASS}>{saving ? '保存中…' : '保存员工档案'}</Button>
            </SheetFooter>
          </form>
        )}
      </SheetContent>
    </Sheet>
  );
}

function NativeSelect({ value, onChange, children }: { value: string; onChange: (value: string) => void; children: ReactNode }) {
  return <select value={value} onChange={(event) => onChange(event.target.value)} className="h-[36px] w-full rounded-[10px] border border-[#e3e7f1] bg-white px-[10px] text-[13px] text-[#464c5e] outline-none focus:border-[#18181a]">{children}</select>;
}

function ImportDialog({
  open,
  file,
  error,
  result,
  importing,
  onOpenChange,
  onFile,
  onImport,
}: {
  open: boolean;
  file: File | null;
  error: string;
  result: EmployeeImportResult | null;
  importing: boolean;
  onOpenChange: (open: boolean) => void;
  onFile: (file: File | undefined) => void;
  onImport: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-32px)] w-[calc(100%-32px)] flex-col gap-0 overflow-hidden rounded-[16px] p-0 sm:max-w-[680px]">
        <div className="shrink-0 border-b border-[#edf0f5] px-[24px] py-[18px]">
          <DialogTitle className="text-[16px] font-semibold text-[#24262d]">导入员工</DialogTitle>
          <DialogDescription className="mt-[6px] text-[12px] leading-[19px] text-[#858b9c]">上传 CSV 或 XLSX；系统会逐行返回创建、更新或错误结果。</DialogDescription>
        </div>
        <div className="min-h-0 overflow-y-auto px-[24px] py-[20px]">
          <label className="grid cursor-pointer gap-[8px] rounded-[14px] border border-dashed border-[#cbd5e5] bg-[#fafcff] px-[18px] py-[20px] text-center">
            <span className="text-[13px] font-medium text-[#464c5e]">选择 CSV 或 XLSX 文件</span>
            <input type="file" accept=".csv,.xlsx" onChange={(event) => onFile(event.target.files?.[0])} className="mx-auto block max-w-full text-[12px] text-[#757f9c] file:mr-[10px] file:rounded-[8px] file:border-0 file:bg-[#edf3ff] file:px-[10px] file:py-[6px] file:text-[11px] file:text-[#1a71ff]" />
            {file && <span className="text-[12px] font-medium text-[#1a71ff]">{file.name}</span>}
          </label>
          {error && <p role="alert" className="mt-[12px] mb-0 rounded-[10px] bg-[#fce7e7] px-[12px] py-[9px] text-[12px] text-[#d20b0b]">{error}</p>}
          {result && <ImportReport result={result} />}
        </div>
        <DialogFooter className={`${DIALOG_FOOTER_CLASS} shrink-0 border-t border-[#edf0f5]`}>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={importing} className={DIALOG_CANCEL_BUTTON_CLASS}>关闭</Button>
          {file && !result && <Button type="button" onClick={onImport} disabled={importing} className={DIALOG_PRIMARY_BUTTON_CLASS}>{importing ? '导入中…' : '开始导入'}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ImportReport({ result }: { result: EmployeeImportResult }) {
  return (
    <section aria-label="员工导入结果" className="mt-[16px] space-y-[12px]">
      <div className="grid grid-cols-2 gap-[10px]">
        <p className="m-0 rounded-[10px] bg-[#e9f7ef] px-[12px] py-[10px] text-[12px] font-medium text-[#018434]">新增 {result.created} 人</p>
        <p className="m-0 rounded-[10px] bg-[#edf4ff] px-[12px] py-[10px] text-[12px] font-medium text-[#1a71ff]">更新 {result.updated} 人</p>
      </div>
      {result.results.length > 0 && (
        <div className="overflow-hidden rounded-[10px] border border-[#edf0f5]">
          {result.results.map((row) => (
            <div key={`${row.row}-${row.username}`} className="border-b border-[#edf0f5] px-[12px] py-[9px] text-[11px] last:border-0">
              <div className="grid grid-cols-[52px_1fr_auto] gap-[10px]">
                <span className="text-[#9aa1b3]">第 {row.row} 行</span>
                <span className="truncate font-medium text-[#464c5e]">{row.username}</span>
                <span className={row.status === 'created' ? 'text-[#018434]' : 'text-[#1a71ff]'}>{row.status === 'created' ? '已创建' : '已更新'}</span>
              </div>
              {row.password && (
                <p className="mt-[7px] mb-0 rounded-[7px] bg-[#fff7e8] px-[9px] py-[6px] font-mono text-[#8a5a00]">
                  {`临时密码：${row.password}`}
                  <span className="ml-[8px] font-sans text-[#9a7850]">仅显示一次，请妥善保存</span>
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      {result.errors.length > 0 ? (
        <div className="overflow-hidden rounded-[10px] border border-[#f1d4d4]">
          {result.errors.map((row) => (
            <div key={`${row.row}-${row.code}`} className="grid gap-[4px] border-b border-[#f3e1e1] px-[12px] py-[9px] text-[11px] last:border-0 sm:grid-cols-[58px_150px_1fr] sm:gap-[10px]">
              <span className="font-medium text-[#d20b0b]">第 {row.row} 行</span>
              <span className="font-mono text-[#a84848]">{row.code}</span>
              <span className="text-[#757f9c]">{row.message}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="m-0 text-[11px] text-[#018434]">全部行处理成功，没有行级错误。</p>
      )}
    </section>
  );
}
