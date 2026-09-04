# QuantXY Enterprise Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable enterprise workbench where AI plans work and real employee accounts own, execute, collaborate on, and review tasks.

**Architecture:** Add an isolated `workbench` backend domain for human organization, projects, plans, tasks, dependencies, and events while preserving the existing Agent/TeamTask domain. Expose one FastAPI router and a React workbench route family; existing digital employees remain optional assistants bound to employee profiles.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, Pydantic v2, existing StaffDeck LLM client, React 18, TypeScript 5.7, Tailwind 4, shadcn/Radix, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-04-quantxy-enterprise-workbench-design.md`

## Global Constraints

- Real users (`User`) are the accountable work principals; `AgentProfile` remains an optional AI assistant.
- Never copy or use the API credential embedded in the supplied HTML prototype.
- All backend reads and writes must enforce `tenant_id`; business actions must also enforce CEO/admin, manager, or member scope.
- Dashboard metrics must come from persisted records; never render fabricated revenue or operational metrics.
- Planning preview never creates tasks; dispatch is transactional and idempotent.
- Model-generated WBS is untrusted and must pass schema validation, normalization, size limits, and dependency-cycle checks.
- Existing CEO, QuantXY brand, avatar, seed, Agent, knowledge, skill, SOP, tool, channel, and team behavior must remain intact.
- Desktop-first UI must remain usable at narrow widths; status meaning may not rely on color alone.

---

## File Map

### Backend domain

- `backend/app/db/models.py`: persisted workbench tables only.
- `backend/app/workbench/schema.py`: API request/response contracts and enums.
- `backend/app/workbench/permissions.py`: business-role visibility and mutation checks.
- `backend/app/workbench/service.py`: organization/project/task state transitions and dashboard aggregation.
- `backend/app/workbench/planner.py`: WBS validation, matching, scheduling, three variants, model fallback.
- `backend/app/workbench/importer.py`: CSV/XLSX employee row parsing and validation.
- `backend/app/api/workbench.py`: thin authenticated HTTP router.
- `backend/app/main.py`: router registration.
- `backend/pyproject.toml`: `openpyxl` runtime dependency for XLSX import.
- `backend/tests/test_workbench_*.py`: isolated domain/API/planner/import tests.

### Frontend domain

- `frontend-enterprise/src/types/workbench.ts`: shared workbench DTOs and status enums.
- `frontend-enterprise/src/pages/workbench/workbenchApi.ts`: typed API calls.
- `frontend-enterprise/src/pages/workbench/workbenchModel.ts`: presentation helpers, labels, grouping, progress math.
- `frontend-enterprise/src/pages/workbench/WorkbenchLayout.tsx`: page header and role-aware tabs.
- `frontend-enterprise/src/pages/workbench/WorkbenchDashboardPage.tsx`: CEO/manager/employee dashboard.
- `frontend-enterprise/src/pages/workbench/ProjectsPage.tsx`: project list and creation.
- `frontend-enterprise/src/pages/workbench/PlanningPage.tsx`: three-step AI planning flow.
- `frontend-enterprise/src/pages/workbench/TasksPage.tsx`: Kanban/list and task detail drawer.
- `frontend-enterprise/src/pages/workbench/MyWorkPage.tsx`: employee-focused work queue.
- `frontend-enterprise/src/pages/workbench/OrganizationPage.tsx`: departments, employee profiles, import.
- `frontend-enterprise/src/pages/workbench/components/*`: focused KPI, status, task, plan, and employee components.
- `frontend-enterprise/src/App.tsx`, `enums/routes.ts`, `components/AppSidebar.tsx`: route and navigation integration.
- `frontend-enterprise/src/pages/workbench/*.test.tsx`, `workbenchModel.test.ts`: behavior and regression tests.

---

### Task 1: Persisted Workbench Model and API Contracts

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/app/workbench/__init__.py`
- Create: `backend/app/workbench/schema.py`
- Test: `backend/tests/test_workbench_models.py`

**Interfaces:**
- Produces SQLModel classes: `Department`, `EmployeeProfile`, `WorkProject`, `WorkPlan`, `WorkTask`, `WorkTaskDependency`, `WorkTaskEvent`.
- Produces Pydantic DTOs used by all later tasks: `DepartmentRead`, `EmployeeRead`, `ProjectRead`, `PlanPreviewRequest`, `PlanRead`, `TaskRead`, `DashboardRead`, `TaskUpdateRequest`, `TaskReviewRequest`.

- [ ] **Step 1: Write failing model tests**

Create an in-memory SQLite engine, call `SQLModel.metadata.create_all`, persist one user, department, employee profile, project, plan, two dependent tasks, and one event. Assert unique employee/user and task dependency constraints raise `IntegrityError`, JSON fields round-trip, and defaults are exactly `active`, `draft`, `backlog`, `0`, and version `0`.

```python
def test_workbench_models_round_trip(db: Session, user: User) -> None:
    dept = Department(tenant_id=user.tenant_id, name="技术部", code="TECH")
    db.add(dept)
    db.flush()
    employee = EmployeeProfile(
        tenant_id=user.tenant_id,
        user_id=user.id,
        department_id=dept.id,
        job_title="后端工程师",
        business_role="member",
        skills_json=["Python", "FastAPI"],
    )
    db.add(employee)
    db.commit()
    assert employee.status == "active"
    assert employee.skills_json == ["Python", "FastAPI"]
```

- [ ] **Step 2: Run the focused test and confirm the imports fail**

Run: `cd backend && pytest tests/test_workbench_models.py -q`
Expected: FAIL because workbench model classes do not exist.

- [ ] **Step 3: Add the seven SQLModel tables**

Use existing `new_id()` and `utc_now()` helpers. Add tenant and lookup indexes, JSON columns via `Column(JSON)`, and these database constraints:

```python
UniqueConstraint("tenant_id", "name", name="uq_workbench_department_tenant_name")
UniqueConstraint("tenant_id", "user_id", name="uq_workbench_employee_tenant_user")
UniqueConstraint("task_id", "depends_on_task_id", name="uq_workbench_task_dependency")
UniqueConstraint("tenant_id", "dispatch_idempotency_key", name="uq_workbench_plan_dispatch_key")
```

Store `date` fields as nullable `date`, monetary values as `float`, capacity as integer 0–100, and version as an integer.

- [ ] **Step 4: Add strict request/response schemas**

Define literal types for business roles and statuses. Set `extra="forbid"` on mutation requests. Use `ConfigDict(from_attributes=True)` for reads. `TaskRead` must include `dependencies: list[str]` and `events: list[WorkTaskEventRead]`; `PlanRead` must expose normalized `variants` without leaking model credentials.

- [ ] **Step 5: Run focused tests**

Run: `cd backend && pytest tests/test_workbench_models.py -q`
Expected: PASS.

- [ ] **Step 6: Commit the task**

```bash
git add backend/app/db/models.py backend/app/workbench backend/tests/test_workbench_models.py
git commit -m "feat: add human workbench data model"
```

---

### Task 2: Organization, Permissions, and Employee Import

**Files:**
- Create: `backend/app/workbench/permissions.py`
- Create: `backend/app/workbench/importer.py`
- Create: `backend/app/workbench/service.py`
- Create: `backend/app/api/workbench.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_workbench_organization_api.py`
- Test: `backend/tests/test_workbench_import.py`

**Interfaces:**
- Produces `WorkbenchAccess` and functions `employee_for_user(db, tenant_id, user_id)`, `require_global_manager(...)`, `can_view_employee(...)`, `can_manage_employee(...)`.
- Produces `/api/enterprise/workbench/departments` and `/employees` CRUD/list APIs plus `/employees/import`.
- `parse_employee_upload(filename: str, content: bytes) -> list[EmployeeImportRow]` is consumed by the API.

- [ ] **Step 1: Write failing permission matrix tests**

Create CEO/admin, department manager, same-department member, other-department member, and cross-tenant user. Assert:

```python
assert WorkbenchAccess.for_user(db, tenant, ceo).can_view_all
assert access_for(manager).can_manage_department(manager_profile.department_id)
assert not access_for(member).can_manage_department(member_profile.department_id)
assert not can_view_employee(db, tenant, member, other_profile)
```

API tests must assert 401 without auth, 403 outside scope, and 404 rather than cross-tenant leakage.

- [ ] **Step 2: Run permission/API tests and confirm failure**

Run: `cd backend && pytest tests/test_workbench_organization_api.py -q`
Expected: FAIL because router and access helpers do not exist.

- [ ] **Step 3: Implement permission helpers and organization service**

`admin` system role and employee `business_role == "ceo"` get global access. Managers get their department. Members get self plus employees participating in the same visible project only where needed by task APIs. Centralize checks; endpoints must not duplicate role logic.

- [ ] **Step 4: Implement organization endpoints**

Use the authenticated user dependency already used by `api/teams.py`. Create/update employee records only for existing same-tenant `User` rows. Delete operations deactivate records with active assignments instead of deleting them. Return employee display name/avatar from `User` joined with profile data.

- [ ] **Step 5: Write failing CSV/XLSX parser tests**

Cover UTF-8 CSV, XLSX bytes, Chinese headers, normalized skill separators, invalid capacity, missing username, duplicate username, and partial success. Required input columns are `username`, `display_name`, `department`; supported optional columns are `employee_no`, `job_title`, `business_role`, `level`, `skills`, `capacity_percent`, `daily_cost`, `manager_username`, `assistant_agent_id`.

- [ ] **Step 6: Implement import parsing and endpoint**

Add `openpyxl>=3.1.5` to runtime dependencies. The endpoint accepts `.csv` and `.xlsx`, caps the file at 5 MiB and 2,000 rows, creates missing non-admin user accounts with a one-time random password, and returns:

```json
{"created": 2, "updated": 1, "errors": [{"row": 4, "code": "unknown_manager", "message": "负责人账号不存在"}]}
```

Never return generated passwords after the response that created them; include them only in each successful newly-created row result so the administrator can distribute them once.

- [ ] **Step 7: Register the router and run tests**

Run: `cd backend && pytest tests/test_workbench_organization_api.py tests/test_workbench_import.py -q`
Expected: PASS.

- [ ] **Step 8: Commit the task**

```bash
git add backend/app/workbench backend/app/api/workbench.py backend/app/main.py backend/pyproject.toml backend/tests/test_workbench_organization_api.py backend/tests/test_workbench_import.py
git commit -m "feat: add real employee organization APIs"
```

---

### Task 3: Human Projects, Tasks, Events, and State Machine

**Files:**
- Modify: `backend/app/workbench/service.py`
- Modify: `backend/app/api/workbench.py`
- Test: `backend/tests/test_workbench_tasks_api.py`

**Interfaces:**
- Produces `create_project`, `list_visible_projects`, `create_task`, `update_task`, `submit_task`, `review_task`, `activate_ready_tasks`, `dashboard_for_user`.
- Produces project, dashboard, task list/detail, comment, submit, review endpoints.
- Status transitions are exported as `WORK_TASK_TRANSITIONS` for planner dispatch and tests.

- [ ] **Step 1: Write failing task-state and scope tests**

Test the exact transition graph and submit payload `{result_summary, artifact_refs}` so existing uploaded resource identifiers are preserved in the audit event:

```python
WORK_TASK_TRANSITIONS = {
    "blocked": {"backlog", "canceled"},
    "backlog": {"in_progress", "canceled"},
    "in_progress": {"review", "canceled"},
    "review": {"done", "in_progress"},
    "done": set(),
    "canceled": set(),
}
```

Assert only assignee/manager can start and submit, only reviewer/manager can approve or return, comments follow visibility scope, and every mutation creates an event with actor and old/new status.

- [ ] **Step 2: Write failing dependency and optimistic-lock tests**

Create A → B → C. Assert B/C begin blocked, completing A activates B only, completing B activates C, a cycle is rejected with 422, and an update with stale `version` returns 409 without overwriting the record.

- [ ] **Step 3: Run focused tests**

Run: `cd backend && pytest tests/test_workbench_tasks_api.py -q`
Expected: FAIL because work APIs are absent.

- [ ] **Step 4: Implement project and task services**

Use service-level transactions. Validate all related IDs share the request tenant. Compute project progress from persisted non-canceled tasks. Record `project_created`, `task_created`, `task_assigned`, `task_started`, `progress_updated`, `comment_added`, `result_submitted`, `review_approved`, `review_returned`, and `dependency_unblocked` events.

- [ ] **Step 5: Implement task/project/dashboard endpoints**

`GET /dashboard` returns role-aware metrics, workload rows, pending reviews, at-risk tasks, project summaries, and latest visible events. `GET /tasks?scope=mine|department|all&status=...` applies permission rules on the server. `PUT /tasks/{id}` requires the current version.

- [ ] **Step 6: Run focused and existing team tests**

Run: `cd backend && pytest tests/test_workbench_tasks_api.py tests/test_teams_api.py tests/test_teams_ops.py -q`
Expected: PASS; the existing Agent team domain remains unchanged.

- [ ] **Step 7: Commit the task**

```bash
git add backend/app/workbench/service.py backend/app/api/workbench.py backend/tests/test_workbench_tasks_api.py
git commit -m "feat: add human project and task workflow"
```

---

### Task 4: Explainable Planning, Matching, and Idempotent Dispatch

**Files:**
- Create: `backend/app/workbench/planner.py`
- Modify: `backend/app/workbench/service.py`
- Modify: `backend/app/api/workbench.py`
- Test: `backend/tests/test_workbench_planner.py`
- Test: `backend/tests/test_workbench_plans_api.py`

**Interfaces:**
- Produces `PlanningTask`, `PlanVariant`, `PlanResult` schemas.
- Produces `build_plan(db, request, current_user) -> WorkPlan`, `dispatch_plan(db, plan_id, variant_key, idempotency_key, current_user) -> list[WorkTask]`.
- Produces `POST /plans/preview`, `GET /plans/{id}`, and `POST /plans/{id}/dispatch`.

- [ ] **Step 1: Write failing deterministic planner tests**

Use five employees with distinct roles, skills, capacity, cost, and current work. Assert role/skill matches rank above cheap unqualified employees, overloaded employees lose capacity score, unstaffed work remains unassigned with a reason, dependencies are acyclic, and A/B/C differ in duration/cost or assignments.

- [ ] **Step 2: Write failing model-output validation tests**

Mock `LLMClient.generate_json` to return valid WBS, malformed JSON, 40 tasks, unknown dependency IDs, self-dependency, and a cycle. Valid output is normalized; invalid output invokes `fallback_wbs(goal)` and sets `source == "fallback"` without surfacing secrets.

- [ ] **Step 3: Run planner tests**

Run: `cd backend && pytest tests/test_workbench_planner.py -q`
Expected: FAIL because planner functions do not exist.

- [ ] **Step 4: Implement WBS generation and validation**

Resolve the tenant default model using the existing model configuration resolver. Use a strict system prompt requesting 6–16 tasks and JSON fields `key`, `title`, `description`, `required_role`, `skills`, `estimate_days`, `priority`, `depends_on`, `acceptance_criteria`. Cap goal/constraints input at 4,000/2,000 characters. Catch provider, timeout, JSON, and validation failures and fall back to a six-stage enterprise delivery template.

- [ ] **Step 5: Implement matching and scheduling**

Normalize case and Chinese separators for keyword matching. Score role 40, skills 30, capacity 20, continuity 10; include the numeric components and human-readable rationale in each assignment. Topologically schedule tasks on working days, honor one employee's capacity, compute critical path, peak parallelism, cost, risk list, and utilization.

- [ ] **Step 6: Implement three variants**

- A balanced: base score and capacity ceiling 100%.
- B fast: choose earliest-qualified assignee and allow 120% warned capacity.
- C cost: weight qualified employee cost after a hard role/skill floor.

Persist the normalized variants in `WorkPlan.variants_json`. Do not persist model credentials or raw provider responses.

- [ ] **Step 7: Write and pass dispatch API tests**

Assert preview creates only one `WorkPlan`, dispatch creates tasks/dependencies in a transaction, selected assignments/dates survive, repeated `idempotency_key` returns the same task IDs, unauthorized dispatch is 403, and a second different key after dispatch is 409.

Run: `cd backend && pytest tests/test_workbench_planner.py tests/test_workbench_plans_api.py -q`
Expected: PASS.

- [ ] **Step 8: Commit the task**

```bash
git add backend/app/workbench/planner.py backend/app/workbench/service.py backend/app/api/workbench.py backend/tests/test_workbench_planner.py backend/tests/test_workbench_plans_api.py
git commit -m "feat: add explainable AI work planning"
```

---

### Task 5: Workbench Routes, Navigation, Types, and API Client

**Files:**
- Create: `frontend-enterprise/src/types/workbench.ts`
- Create: `frontend-enterprise/src/pages/workbench/workbenchApi.ts`
- Create: `frontend-enterprise/src/pages/workbench/workbenchModel.ts`
- Create: `frontend-enterprise/src/pages/workbench/WorkbenchLayout.tsx`
- Modify: `frontend-enterprise/src/enums/routes.ts`
- Modify: `frontend-enterprise/src/App.tsx`
- Modify: `frontend-enterprise/src/components/AppSidebar.tsx`
- Modify: `frontend-enterprise/src/components/AppSidebar.test.tsx`
- Create: `frontend-enterprise/src/pages/workbench/workbenchModel.test.ts`
- Create: `frontend-enterprise/src/pages/workbench/WorkbenchRouting.test.tsx`

**Interfaces:**
- Produces routes `/enterprise/workbench`, `/projects`, `/planning`, `/tasks`, `/my-work`, `/organization` under the enterprise prefix.
- Produces typed `workbenchApi` consumed by all UI pages.
- Produces `taskStatusLabel`, `taskStatusTone`, `groupTasksByStatus`, `projectProgress`, `formatWorkload`.

- [ ] **Step 1: Write failing navigation and model tests**

Assert the sidebar shows the six workbench links above the existing AI capability links; `/enterprise` redirects to `/enterprise/workbench`; legacy `/enterprise/dashboard`, Agents, knowledge, skills, SOP, tools, channels, and admin settings still resolve. Assert task labels and grouping are exhaustive for all six statuses.

- [ ] **Step 2: Run focused frontend tests**

Run: `cd frontend-enterprise && npm test -- src/pages/workbench/workbenchModel.test.ts src/pages/workbench/WorkbenchRouting.test.tsx src/components/AppSidebar.test.tsx`
Expected: FAIL because routes and helpers do not exist.

- [ ] **Step 3: Add workbench DTOs and typed API methods**

Mirror backend field names exactly. Export functions `getDashboard`, `listProjects`, `createProject`, `previewPlan`, `dispatchPlan`, `listTasks`, `getTask`, `updateTask`, `commentTask`, `submitTask`, `reviewTask`, `listDepartments`, `createDepartment`, `listEmployees`, `updateEmployee`, and `importEmployees`.

- [ ] **Step 4: Add route enum values and shell routes**

Lazy loading is not required for this codebase. Route each page explicitly and preserve authentication/admin guards. Select the correct sidebar item for nested workbench paths. Redirect `/enterprise` to `EnterpriseRoute.Workbench`.

- [ ] **Step 5: Restructure sidebar labels without removing existing capability routes**

Groups: `企业运营`, `AI 能力`, `接入与系统`. Use the existing QuantXY `BrandLogo`. Existing “数字员工” wording becomes “AI 助理” only in navigation; data types and APIs remain Agent-based.

- [ ] **Step 6: Run focused tests and build type-check**

Run: `cd frontend-enterprise && npm test -- src/pages/workbench/workbenchModel.test.ts src/pages/workbench/WorkbenchRouting.test.tsx src/components/AppSidebar.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit the task**

```bash
git add frontend-enterprise/src/types/workbench.ts frontend-enterprise/src/pages/workbench frontend-enterprise/src/enums/routes.ts frontend-enterprise/src/App.tsx frontend-enterprise/src/components/AppSidebar.tsx frontend-enterprise/src/components/AppSidebar.test.tsx
git commit -m "feat: add enterprise workbench routes"
```

---

### Task 6: Dashboard, Projects, and Organization UI

**Files:**
- Create: `frontend-enterprise/src/pages/workbench/components/WorkbenchKpi.tsx`
- Create: `frontend-enterprise/src/pages/workbench/components/WorkloadBar.tsx`
- Create: `frontend-enterprise/src/pages/workbench/components/EmployeeBadge.tsx`
- Create: `frontend-enterprise/src/pages/workbench/WorkbenchDashboardPage.tsx`
- Create: `frontend-enterprise/src/pages/workbench/ProjectsPage.tsx`
- Create: `frontend-enterprise/src/pages/workbench/OrganizationPage.tsx`
- Test: `frontend-enterprise/src/pages/workbench/WorkbenchDashboardPage.test.tsx`
- Test: `frontend-enterprise/src/pages/workbench/OrganizationPage.test.tsx`

**Interfaces:**
- Consumes `workbenchApi`, auth context passed through existing `Shell`, and shared DTOs.
- Produces role-aware operational dashboard, project creation/list, department/employee management, and import result UI.

- [ ] **Step 1: Write failing dashboard tests**

Mock API responses and assert CEO sees company metrics, pending reviews, workload, risks, and activity; member sees only own work metrics and no global cost. Assert zero-data responses render useful empty states rather than fake numbers.

- [ ] **Step 2: Write failing organization tests**

Assert admin can create a department, edit an employee, bind an existing AI assistant, upload CSV/XLSX, and see created/updated/row-error results. Assert a member receives a read-only view without mutation controls.

- [ ] **Step 3: Implement focused reusable components**

Use semantic text labels alongside color, existing `EmployeeAvatar`, `Dialog`, `Drawer/Sheet`, `DataTable` where suitable, and existing toast helpers. Components receive data and callbacks; they do not call APIs directly.

- [ ] **Step 4: Implement dashboard and project pages**

Use responsive grids (`1 / 2 / 4` columns), real API aggregates, skeletons, retry states, and role-aware copy. Project cards calculate progress from returned task totals and link to filtered tasks/planning with `project_id` in the query string.

- [ ] **Step 5: Implement organization page**

Include department chips, search, employee table/cards, capacity bar, skills, role, department, daily cost, and assistant binding. Import accepts only `.csv,.xlsx`, previews the file name, and renders the backend row-level report.

- [ ] **Step 6: Run focused tests**

Run: `cd frontend-enterprise && npm test -- src/pages/workbench/WorkbenchDashboardPage.test.tsx src/pages/workbench/OrganizationPage.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit the task**

```bash
git add frontend-enterprise/src/pages/workbench
git commit -m "feat: add workbench dashboard and organization"
```

---

### Task 7: AI Planning, Task Collaboration, and My Work UI

**Files:**
- Create: `frontend-enterprise/src/pages/workbench/components/PlanComparison.tsx`
- Create: `frontend-enterprise/src/pages/workbench/components/TaskCard.tsx`
- Create: `frontend-enterprise/src/pages/workbench/components/TaskDetailSheet.tsx`
- Create: `frontend-enterprise/src/pages/workbench/PlanningPage.tsx`
- Create: `frontend-enterprise/src/pages/workbench/TasksPage.tsx`
- Create: `frontend-enterprise/src/pages/workbench/MyWorkPage.tsx`
- Test: `frontend-enterprise/src/pages/workbench/PlanningPage.test.tsx`
- Test: `frontend-enterprise/src/pages/workbench/TasksPage.test.tsx`

**Interfaces:**
- Consumes Task 5 API/types and Task 6 components.
- Produces the user-visible goal → plan → dispatch and human collaboration loop.

- [ ] **Step 1: Write failing planning-flow tests**

Submit a goal and assert loading, server validation error, fallback source badge, WBS editing, A/B/C metrics, assignment rationale, unassigned warning, variant selection, confirmation, one dispatch request with a stable idempotency key, and navigation to created tasks.

- [ ] **Step 2: Write failing task-flow tests**

Assert Kanban status columns, filters, task detail dependencies/events, member start/comment/submit actions, manager approve/return actions, 409 refresh handling, and blocked-task disabled actions. Assert narrow viewport keeps status labels and makes detail full-screen.

- [ ] **Step 3: Implement the three-step planning page**

Step 1 collects project, goal, deadline, budget, and constraints. Step 2 renders editable WBS and three plan cards with cost, completion date, utilization, critical path, risk, and rationale. Step 3 shows a confirmation summary and dispatches only after explicit confirmation.

- [ ] **Step 4: Implement task board and detail sheet**

Keep server state authoritative. After each mutation refetch detail and list. Display events chronologically, dependency links, acceptance criteria, result summary, reviewer comment, version conflict message, and accessible action labels.

- [ ] **Step 5: Implement My Work**

Show role-aware headline, in-progress/review/overdue counts, today priority list, pending submissions, recent collaboration events, and workload. Reuse `TaskDetailSheet` so employee actions behave identically across pages.

- [ ] **Step 6: Run focused tests and build**

Run: `cd frontend-enterprise && npm test -- src/pages/workbench/PlanningPage.test.tsx src/pages/workbench/TasksPage.test.tsx && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit the task**

```bash
git add frontend-enterprise/src/pages/workbench
git commit -m "feat: complete human work planning workflow"
```

---

### Task 8: Seed, Integration Regression, and Local Deployment Verification

**Files:**
- Modify: `backend/app/db/seed.py` or add a focused `backend/app/db/workbench_seed.py`
- Test: `backend/tests/test_workbench_seed.py`
- Modify: `backend/app/db/seed.py`

**Interfaces:**
- Produces idempotent QuantXY demo organization/project/task data for a fresh database without overwriting user data.
- Verifies the whole product at `http://127.0.0.1:5173`.

- [ ] **Step 1: Write failing idempotent seed test**

On a blank database, seed CEO plus sales, operations, delivery, technology, administration, and finance departments with a small real-user roster, one sample project, and representative task dependencies. Run seed twice and assert counts and IDs remain stable. Do not insert fabricated revenue metrics.

- [ ] **Step 2: Implement the minimal seed**

Use deterministic IDs/names and only create records when the tenant has no workbench organization. Reuse existing demo users where possible. Preserve the previously added CEO profile, QuantXY logo, and CEO avatar.

- [ ] **Step 3: Run complete backend regression**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 4: Run complete frontend regression and checks**

Run: `cd frontend-enterprise && npm test && npm run i18n:check && npm run build`
Expected: PASS.

- [ ] **Step 5: Start/restart the existing local single-port app**

Use the repository's documented startup command/process manager. Do not spawn a second process on port 5173. Confirm:

```bash
curl -fsS http://127.0.0.1:5173/api/health
curl -fsS http://127.0.0.1:5173/enterprise/workbench >/dev/null
```

Expected: health JSON reports `status: ok`; the SPA route returns successfully.

- [ ] **Step 6: Browser smoke test**

With the existing logged-in session, verify sidebar branding and all six workbench routes; generate and dispatch one fallback/model plan; switch to an employee account and progress one task; switch back to CEO and approve it; confirm dashboard/event updates. Check desktop and a narrow viewport. Capture screenshots for final verification.

- [ ] **Step 7: Security and dirty-worktree audit**

Run a secret-pattern scan limited to added files, verify no credential from the HTML exists in the repo, inspect `git status --short`, and confirm unrelated pre-existing edits remain present and unmodified except where deliberately integrated.

- [ ] **Step 8: Commit the integration**

```bash
git add backend/app/db/workbench_seed.py backend/app/db/seed.py backend/tests/test_workbench_seed.py
git commit -m "feat: seed and verify QuantXY workbench"
```

---

## Final Acceptance Checklist

- [ ] A CEO can create or import employees and assign departments/roles.
- [ ] A manager can create a project, preview three explainable plans, edit and dispatch one.
- [ ] Dispatched tasks belong to real `User` accounts and respect dependencies.
- [ ] Employees can log in, collaborate, submit, and see only authorized work.
- [ ] Managers/CEO can approve or return with a recorded reason.
- [ ] Dashboard metrics and activity reflect persisted operations.
- [ ] Digital employees, knowledge, skills, SOPs, tools, channels, teams, and existing branding still work.
- [ ] No browser-visible or repository-embedded model credential was introduced.
- [ ] Backend suite, frontend suite, i18n check, TypeScript build, and browser smoke pass.
