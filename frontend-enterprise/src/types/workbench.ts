export type BusinessRole = 'admin' | 'ceo' | 'manager' | 'member';
export type WorkbenchDirectoryScope = 'all' | 'department' | 'self';
export type DepartmentStatus = 'active' | 'archived';
export type EmployeeStatus = 'active' | 'inactive';
export type ProjectStatus = 'active' | 'on_hold' | 'completed' | 'archived';
export type ProjectHealth = 'on_track' | 'at_risk' | 'off_track';
export type PlanStatus = 'draft' | 'approved' | 'dispatched' | 'failed';
export type PlanSource = 'model' | 'fallback';
export type TaskStatus = 'backlog' | 'blocked' | 'in_progress' | 'review' | 'done' | 'canceled';
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent';
export type TaskScope = 'mine' | 'department' | 'all';
export type ReviewVerdict = 'approve' | 'rework';
export type PlanVariantKey = 'A' | 'B' | 'C';

export type WorkbenchAccessRead = {
  tenant_id: string;
  user_id: string;
  business_role: BusinessRole;
  directory_scope: WorkbenchDirectoryScope;
  can_create_project: boolean;
};

export type DepartmentRead = {
  id: string;
  tenant_id: string;
  name: string;
  code: string;
  parent_id: string | null;
  manager_user_id: string | null;
  status: DepartmentStatus;
  created_at: string;
  updated_at: string;
};

export type EmployeeRead = {
  id: string;
  tenant_id: string;
  user_id: string;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  employee_no: string | null;
  department_id: string | null;
  job_title: string | null;
  business_role: BusinessRole;
  level: string | null;
  skills: string[];
  capacity_percent: number;
  daily_cost: number | null;
  manager_user_id: string | null;
  assistant_agent_id: string | null;
  status: EmployeeStatus;
  created_at: string;
  updated_at: string;
};

export type ProjectRead = {
  id: string;
  tenant_id: string;
  name: string;
  objective: string;
  description: string | null;
  owner_user_id: string | null;
  department_id: string | null;
  status: ProjectStatus;
  health: ProjectHealth;
  start_date: string | null;
  due_date: string | null;
  budget: number | null;
  version: number;
  task_total: number;
  task_done: number;
  progress: number;
  created_at: string;
  updated_at: string;
};

export type PlanningTask = {
  key: string;
  title: string;
  description: string;
  required_role: string;
  skills: string[];
  estimate_days: number;
  priority: TaskPriority;
  depends_on: string[];
  acceptance_criteria: string;
  assignee_user_id: string | null;
  start_date: string | null;
  due_date: string | null;
  assignment: {
    score_components?: Record<string, number>;
    total_score?: number;
    effective_capacity_percent?: number;
    candidate_scores?: Record<string, Record<string, number>>;
    rationale?: string;
    [key: string]: unknown;
  };
  unassigned_reason: string | null;
};

export type PlanVariantMetrics = {
  start_date?: string;
  finish_date?: string;
  duration_workdays?: number;
  cost?: number;
  critical_path?: string[];
  peak_parallelism?: number;
  effective_capacity_percent?: Record<string, number>;
  [key: string]: unknown;
};

export type PlanVariant = {
  key: PlanVariantKey;
  name: string;
  strategy: 'balanced' | 'fast' | 'cost';
  tasks: PlanningTask[];
  metrics: PlanVariantMetrics;
  risks: string[];
  utilization: Record<string, {
    assigned_days: number;
    capacity_percent: number;
    utilization_percent: number;
    [key: string]: number;
  }>;
};

export type PlanRead = {
  id: string;
  tenant_id: string;
  project_id: string;
  created_by_user_id: string;
  goal: string;
  deadline: string | null;
  budget: number | null;
  constraints: Record<string, unknown>;
  status: PlanStatus;
  source: PlanSource;
  variants: PlanVariant[];
  selected_variant: PlanVariantKey | null;
  dispatch_idempotency_key: string | null;
  created_at: string;
  updated_at: string;
  dispatched_at: string | null;
};

export type WorkTaskEventRead = {
  id: string;
  task_id: string;
  tenant_id: string;
  actor_user_id: string | null;
  actor_type: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type TaskRead = {
  id: string;
  tenant_id: string;
  project_id: string;
  plan_id: string | null;
  parent_task_id: string | null;
  title: string;
  description: string | null;
  required_role: string | null;
  priority: TaskPriority;
  status: TaskStatus;
  assignee_user_id: string | null;
  reviewer_user_id: string | null;
  start_date: string | null;
  due_date: string | null;
  estimate_days: number | null;
  progress: number;
  acceptance_criteria: string | null;
  result_summary: string | null;
  version: number;
  dependencies: string[];
  events: WorkTaskEventRead[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type WorkloadRow = {
  user_id: string;
  department_id: string | null;
  capacity_percent: number;
  active_task_count: number;
  estimate_days: number;
};

export type DashboardRead = {
  tenant_id: string;
  project_count: number;
  task_counts: Partial<Record<TaskStatus, number>>;
  employee_count: number;
  pending_review_count: number;
  at_risk_project_count: number;
  department_loads: WorkloadRow[];
  workload_rows: WorkloadRow[];
  pending_reviews: TaskRead[];
  at_risk_tasks: TaskRead[];
  project_summaries: ProjectRead[];
  recent_events: WorkTaskEventRead[];
};

export type ProjectCreateRequest = {
  tenant_id: string;
  name: string;
  objective: string;
  description?: string | null;
  owner_user_id?: string | null;
  department_id: string;
  status?: ProjectStatus;
  health?: ProjectHealth;
  start_date?: string | null;
  due_date?: string | null;
  budget?: number | null;
};

export type PlanPreviewRequest = {
  tenant_id: string;
  project_id: string;
  goal?: string | null;
  deadline?: string | null;
  budget?: number | null;
  constraints?: Record<string, unknown>;
};

export type PlanDispatchRequest = {
  tenant_id: string;
  variant_key: PlanVariantKey;
  idempotency_key: string;
};

export type TaskListQuery = {
  tenant_id?: string;
  scope?: TaskScope;
  status?: TaskStatus;
  project_id?: string;
};

export type TaskUpdateRequest = {
  tenant_id: string;
  version: number;
  title?: string;
  description?: string | null;
  priority?: TaskPriority;
  status?: TaskStatus;
  assignee_user_id?: string | null;
  reviewer_user_id?: string | null;
  start_date?: string | null;
  due_date?: string | null;
  estimate_days?: number | null;
  progress?: number;
  acceptance_criteria?: string | null;
  dependencies?: string[];
};

export type TaskCommentRequest = {
  tenant_id: string;
  version: number;
  comment: string;
};

export type TaskSubmitRequest = {
  tenant_id: string;
  version: number;
  result_summary: string;
  artifact_refs?: string[];
};

export type TaskReviewRequest = {
  tenant_id: string;
  version: number;
  verdict: ReviewVerdict;
  comment?: string | null;
};

export type DepartmentCreateRequest = {
  tenant_id: string;
  name: string;
  code: string;
  parent_id?: string | null;
  manager_user_id?: string | null;
};

export type EmployeeUpdateRequest = {
  tenant_id: string;
  employee_no?: string | null;
  department_id?: string | null;
  job_title?: string | null;
  business_role?: BusinessRole;
  level?: string | null;
  skills?: string[];
  capacity_percent?: number;
  daily_cost?: number | null;
  manager_user_id?: string | null;
  assistant_agent_id?: string | null;
  status?: EmployeeStatus;
};

export type EmployeeImportError = {
  row: number;
  code: string;
  message: string;
};

export type EmployeeImportRowResult = {
  row: number;
  username: string;
  status: 'created' | 'updated';
  password?: string;
};

export type EmployeeImportResult = {
  created: number;
  updated: number;
  errors: EmployeeImportError[];
  results: EmployeeImportRowResult[];
};

export type Department = DepartmentRead;
export type Employee = EmployeeRead;
export type WorkProject = ProjectRead;
export type WorkPlan = PlanRead;
export type WorkTask = TaskRead;
export type WorkbenchDashboard = DashboardRead;
