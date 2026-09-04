import { api, ApiError, TENANT_ID } from '@/api/client';
import { getEnterpriseAuthSession } from '@/auth';
import type {
  DashboardRead,
  DepartmentCreateRequest,
  DepartmentRead,
  EmployeeImportResult,
  EmployeeRead,
  EmployeeUpdateRequest,
  PlanDispatchRequest,
  PlanPreviewRequest,
  PlanRead,
  ProjectCreateRequest,
  ProjectRead,
  TaskCommentRequest,
  TaskListQuery,
  TaskRead,
  TaskReviewRequest,
  TaskSubmitRequest,
  TaskUpdateRequest,
} from '@/types/workbench';

const WORKBENCH_API = '/api/enterprise/workbench';

function queryPath(path: string, values: Record<string, string | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') query.set(key, value);
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function resourcePath(resource: string, id: string): string {
  return `${WORKBENCH_API}/${resource}/${encodeURIComponent(id)}`;
}

async function directRequest<T>(path: string, options: RequestInit): Promise<T> {
  const apiBase = import.meta.env.VITE_API_BASE_URL || '';
  const token = getEnterpriseAuthSession()?.token;
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new ApiError(response.status, text, response.statusText);
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : {}) as T;
}

export function getDashboard(tenantId = TENANT_ID): Promise<DashboardRead> {
  return api.get(queryPath(`${WORKBENCH_API}/dashboard`, { tenant_id: tenantId }));
}

export function listProjects(tenantId = TENANT_ID): Promise<ProjectRead[]> {
  return api.get(queryPath(`${WORKBENCH_API}/projects`, { tenant_id: tenantId }));
}

export function createProject(request: ProjectCreateRequest): Promise<ProjectRead> {
  return api.post(`${WORKBENCH_API}/projects`, request);
}

export function previewPlan(request: PlanPreviewRequest): Promise<PlanRead> {
  return api.post(`${WORKBENCH_API}/plans/preview`, request);
}

export function dispatchPlan(planId: string, request: PlanDispatchRequest): Promise<TaskRead[]> {
  return api.post(`${resourcePath('plans', planId)}/dispatch`, request);
}

export function listTasks(query: TaskListQuery = {}): Promise<TaskRead[]> {
  return api.get(queryPath(`${WORKBENCH_API}/tasks`, {
    tenant_id: query.tenant_id || TENANT_ID,
    scope: query.scope,
    status: query.status,
    project_id: query.project_id,
  }));
}

export function getTask(taskId: string, tenantId = TENANT_ID): Promise<TaskRead> {
  return api.get(queryPath(resourcePath('tasks', taskId), { tenant_id: tenantId }));
}

export function updateTask(taskId: string, request: TaskUpdateRequest): Promise<TaskRead> {
  return api.put(resourcePath('tasks', taskId), request);
}

export function commentTask(taskId: string, request: TaskCommentRequest): Promise<TaskRead> {
  return api.post(`${resourcePath('tasks', taskId)}/comments`, request);
}

export function submitTask(taskId: string, request: TaskSubmitRequest): Promise<TaskRead> {
  return api.post(`${resourcePath('tasks', taskId)}/submit`, request);
}

export function reviewTask(taskId: string, request: TaskReviewRequest): Promise<TaskRead> {
  return api.post(`${resourcePath('tasks', taskId)}/review`, request);
}

export function listDepartments(tenantId = TENANT_ID): Promise<DepartmentRead[]> {
  return api.get(queryPath(`${WORKBENCH_API}/departments`, { tenant_id: tenantId }));
}

export function createDepartment(request: DepartmentCreateRequest): Promise<DepartmentRead> {
  return api.post(`${WORKBENCH_API}/departments`, request);
}

export function listEmployees(tenantId = TENANT_ID): Promise<EmployeeRead[]> {
  return api.get(queryPath(`${WORKBENCH_API}/employees`, { tenant_id: tenantId }));
}

export function updateEmployee(
  employeeId: string,
  request: EmployeeUpdateRequest,
): Promise<EmployeeRead> {
  return directRequest(resourcePath('employees', employeeId), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export function importEmployees(file: File, tenantId = TENANT_ID): Promise<EmployeeImportResult> {
  const form = new FormData();
  form.append('file', file);
  return directRequest(queryPath(`${WORKBENCH_API}/employees/import`, { tenant_id: tenantId }), {
    method: 'POST',
    body: form,
  });
}

export const workbenchApi = {
  getDashboard,
  listProjects,
  createProject,
  previewPlan,
  dispatchPlan,
  listTasks,
  getTask,
  updateTask,
  commentTask,
  submitTask,
  reviewTask,
  listDepartments,
  createDepartment,
  listEmployees,
  updateEmployee,
  importEmployees,
};
