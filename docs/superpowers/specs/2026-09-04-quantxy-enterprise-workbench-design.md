# QuantXY 企业工作台设计

日期：2026-09-04  
状态：已批准进入实施  
范围：首个可运行版本（目标拆解 → 真人分发 → 协同执行 → 审核沉淀）

## 1. 背景与目标

StaffDeck 现有产品以数字员工（`AgentProfile`）为主要工作主体，已经具备知识库、技能、SOP、工具、会话、团队任务、依赖、审计和人工复核能力。用户提供的 QuantXY 企业工作台原型则以真实组织成员为任务责任人，强调管理者输入目标后，由 AI 完成拆解、匹配、排期、方案比较和下发。

本项目把两者组合成一个企业工作台：

- 真人员工是项目、任务、提交、审核和责任归属的主体。
- AI 负责目标理解、任务拆解、候选人匹配、排期、风险提示和进度汇总。
- 原有数字员工保留为真人可调用的 AI 助理与能力容器，不冒充真人，不自动取得真人权限。
- 原有知识库、技能、SOP、工具和模型配置继续复用。
- 所有任务变更和 AI 调度动作可追溯。

首版成功标准：管理员能维护真实组织；管理者能创建目标、获得三套可比较的调度方案并下发；员工登录后能看到自己的任务、推进状态、评论和提交成果；负责人能审核或退回；驾驶舱显示真实数据而非静态 mock。

## 2. 方案比较与决策

### 方案 A：增量双主体（采用）

新增真人组织与工作任务域，保持现有 Agent/TeamTask 域不变。真人任务通过 `user_id` 归属，数字员工通过可选的 `assistant_agent_id` 为真人提供辅助。

优点：迁移风险最低，现有数字员工能力可完整保留，能够快速形成真人闭环；后续仍可演进为统一主体。缺点：短期存在真人任务与 Agent 团队任务两套模型，需要清楚区分。

### 方案 B：统一 Principal 主体

新增 `Principal(human/agent/service)`，把现有 TeamMember、TeamTask、权限和会话整体迁移为多态主体。

优点：长期模型最统一。缺点：会改动大量稳定代码和 API，迁移、权限与回归风险高，不适合首版。

### 方案 C：直接移植单页原型

把 HTML 的 localStorage 数据和页面直接搬进前端。

优点：视觉交付快。缺点：没有真实后端、权限、并发或审计，且原型包含硬编码 API 密钥和静态业务数据，不能用于企业协作。

决策：采用方案 A，并为将来的统一主体预留 `member_type`/`assistant_agent_id` 等清晰边界。

## 3. 首版范围

### 包含

1. 企业驾驶舱：任务、项目、人员负载、待审核、风险和近期动态。
2. 项目中心：项目创建、目标、负责人、周期、预算、进度和任务汇总。
3. AI 调度中心：目标与约束输入、WBS、人员匹配、依赖排期、三方案比较、人工确认和下发。
4. 任务中心：看板、筛选、详情、依赖、状态推进、评论、成果提交和审核退回。
5. 员工工作台：我的任务、待交付、协作动态、负载与快捷入口。
6. 组织与权限：部门、真人账号、岗位、职级、技能、可用率、成本和 AI 助理绑定。
7. 复用入口：知识库、技能、SOP、工具、数字员工和模型设置保持可访问。
8. Excel/CSV 员工批量导入的后端契约和前端上传入口；手工建档作为默认路径。

### 暂不包含

- 飞书、企业微信或外部 HR 系统自动同步。
- 财务总账、CRM、数据仓库等真实经营数据集成。
- 薪资、合同等专业 HRIS 功能。
- 移动端原生应用。
- 把所有现有 TeamTask、ScheduledTask、A2A Task 强制统一成一个数据库实体。

原型中的财务中心和数据洞察保留为后续集成方向，首版不展示虚构经营数字。

## 4. 权限模型

首版采用三级业务权限，并复用现有租户隔离：

- `admin/ceo`：全局查看；维护组织；创建、审批和下发调度方案；跨部门改派；最终验收。
- `manager`：查看本部门及所负责项目；创建项目与目标；在部门内改派；审核部门任务；查看部门负载。
- `member`：查看参与项目与本人任务；评论协作；更新本人任务；提交成果；申请延期或补充信息。

现有 `User.role` 继续承担系统管理员权限；业务角色、部门和岗位存入员工档案。读取与写入均校验 `tenant_id`，任务详情按“全局权限、负责部门、项目参与、本人责任”依次判定。

数字员工的能力不会因为绑定到某员工而自动获得该员工的业务权限。AI 只能读取调度所需的最小化员工档案与被授权的知识资源。

## 5. 数据模型

### `Department`

- `id`, `tenant_id`, `name`, `code`
- `parent_id`（首版允许为空）
- `manager_user_id`
- `status`, `created_at`, `updated_at`
- 同一租户内名称唯一

### `EmployeeProfile`

- `id`, `tenant_id`, `user_id`（一对一）
- `employee_no`, `department_id`, `job_title`, `business_role`, `level`
- `skills_json`
- `capacity_percent`, `daily_cost`
- `manager_user_id`
- `assistant_agent_id`（可选，仅表示可调用的 AI 助理）
- `status`, `created_at`, `updated_at`

### `WorkProject`

- `id`, `tenant_id`, `name`, `objective`, `description`
- `owner_user_id`, `department_id`
- `status`, `health`
- `start_date`, `due_date`, `budget`
- `created_at`, `updated_at`

### `WorkPlan`

- `id`, `tenant_id`, `project_id`, `created_by_user_id`
- `goal`, `deadline`, `budget`, `constraints_json`
- `status`: `draft | approved | dispatched | failed`
- `source`: `model | fallback`
- `variants_json`：三套方案及其指标、任务映射、分配理由和风险
- `selected_variant`
- `dispatch_idempotency_key`（首次下发时写入，同租户唯一）
- `created_at`, `updated_at`, `dispatched_at`

### `WorkTask`

- `id`, `tenant_id`, `project_id`, `plan_id`, `parent_task_id`
- `title`, `description`, `required_role`, `priority`
- `status`: `backlog | blocked | in_progress | review | done | canceled`
- `assignee_user_id`, `reviewer_user_id`
- `start_date`, `due_date`, `estimate_days`, `progress`
- `acceptance_criteria`, `result_summary`
- `version`, `created_at`, `updated_at`, `completed_at`

### `WorkTaskDependency`

- `task_id`, `depends_on_task_id`
- 数据库唯一约束避免重复依赖；服务层阻止自依赖和循环依赖。

### `WorkTaskEvent`

- `id`, `tenant_id`, `task_id`
- `actor_user_id`, `actor_type`
- `event_type`, `payload_json`, `created_at`

评论、状态变化、改派、成果提交、审核与延期申请都写入事件表。首版成果附件复用现有文件/资源上传能力；事件只保存引用与摘要。

## 6. AI 调度与任务流

### 6.1 生成方案

管理者输入战略目标、截止日期、预算和约束。服务端读取同租户可用员工的岗位、技能、容量、当前未完成任务与成本。

若存在可用默认模型，服务端通过现有模型网关请求结构化 WBS；模型只负责提出任务语义、角色、工期、依赖和验收标准，不直接写数据库。输出必须经过 Pydantic schema 校验、任务数量限制、依赖环检测和字段规范化。

若模型不可用、超时或输出无效，则使用内置企业项目模板生成可编辑的兜底 WBS，页面明确标注“内置规划引擎”。

### 6.2 匹配与排期

匹配评分由可解释规则产生：

- 岗位/业务角色匹配 40%
- 技能关键词匹配 30%
- 剩余容量与当前负载 20%
- 同项目/同部门协作连续性 10%

没有合格人员时不强行分配，任务标记为待人工指派并显示原因。

排期使用依赖拓扑排序和人员可用窗口，生成：

- A 均衡方案：综合工期、负载和风险。
- B 快速方案：提高并行度，允许更高峰值负载。
- C 成本方案：优先满足能力前提下的低成本人员。

每个方案展示预计完成日、成本、峰值并发、人员利用率、关键路径、风险和逐任务分配理由。

### 6.3 确认与下发

方案预览不创建任务。只有 `admin/ceo` 或有权的项目负责人确认后，服务端在一个事务中：

1. 锁定计划并确认未重复下发。
2. 创建全部任务与依赖。
3. 为任务记录 `task_created` 与 `task_assigned` 事件。
4. 将计划标记为 `dispatched`。

请求支持幂等键，重复点击不会重复创建任务。

### 6.4 真人执行与审核

员工把任务从待办推进为进行中，可评论、更新进度并提交成果。提交成果后进入 `review`；审核人可通过为 `done`，或附原因退回 `in_progress`。依赖任务完成后，系统自动把可执行任务从 `blocked` 激活为 `backlog`。

所有写操作带 `version`，版本冲突返回 409 并要求前端刷新，避免改派与审核互相覆盖。

## 7. 前端信息架构

管理端侧边栏调整为：

1. 企业工作台
2. 项目中心
3. AI 调度中心
4. 任务中心
5. 员工工作台
6. 组织与权限
7. AI 能力（数字员工、知识库、技能、SOP、工具）
8. 接入与系统（渠道、账号、模型、运行设置）

保留现有 QuantXY 左图标、右字标品牌。页面沿用 StaffDeck 的 React、Tailwind、shadcn 组件与现有圆角卡片语言，吸收原型的浅灰蓝背景、蓝色主行动、状态色、KPI 卡片、甘特和负载表达，但不复制其单文件实现。

### 企业工作台

- 管理者：全局 KPI、战略目标快捷输入、待审核、项目健康、部门负载、风险和近期动态。
- 普通员工：我的进行中、待提交、逾期、今日优先和协作动态。

### AI 调度中心

采用三步界面：目标与约束 → WBS/人员/方案比较 → 确认下发。用户可在下发前修改负责人、日期、验收标准和依赖。

### 任务中心

默认 Kanban，支持列表筛选；详情抽屉显示任务说明、依赖、验收标准、评论/事件、成果与审核动作。

### 响应式

桌面优先；窄屏将多列 KPI 折为 1–2 列、看板横向滚动、详情抽屉全屏。所有仅图标操作提供可访问名称，状态不仅依赖颜色表达。

## 8. API 边界

前缀：`/api/enterprise/workbench`

- `GET/POST /departments`
- `PUT/DELETE /departments/{id}`
- `GET/POST /employees`
- `PUT /employees/{id}`
- `POST /employees/import`（CSV/XLSX；返回逐行成功/错误结果）
- `GET/POST /projects`
- `GET/PUT /projects/{id}`
- `GET /dashboard`
- `POST /plans/preview`
- `GET /plans/{id}`
- `POST /plans/{id}/dispatch`
- `GET/POST /tasks`
- `GET /tasks/{id}`
- `PUT /tasks/{id}`
- `POST /tasks/{id}/comments`
- `POST /tasks/{id}/submit`
- `POST /tasks/{id}/review`

API 返回共享 schema，前端不根据页面自行推导权限或状态机。错误统一包含稳定 `code`、中文可读 `message` 和可选 `details`。

## 9. 安全与可靠性

- 不迁移或使用用户 HTML 中的硬编码 API 密钥；如果该密钥真实有效，应在外部立即轮换。
- 模型凭据仅通过现有服务端模型配置解析，不下发浏览器。
- 所有查询按租户过滤，敏感写操作再校验业务权限。
- 调度输入限制长度，模型输出作为不可信数据校验。
- 下发使用事务和幂等键；任务更新使用乐观锁。
- 删除组织成员时，已有任务保留并阻止硬删除，改为停用档案。
- 仪表盘仅展示数据库聚合结果；无数据时显示空状态，不生成模拟业务数字。

## 10. 测试与验收

### 后端

- 模型、schema 和租户隔离测试。
- CEO、经理、员工三级权限矩阵。
- 依赖环检测、blocked 激活和状态机测试。
- 规划失败兜底、候选匹配、三方案差异测试。
- 下发事务、幂等与重复请求测试。
- 乐观锁冲突、审核退回和事件审计测试。
- CSV/Excel 导入的合法行、重复账号和部分失败测试。

### 前端

- 新路由与侧边栏回归。
- 不同角色驾驶舱内容与可执行按钮。
- AI 调度三步流程、编辑、错误与兜底标识。
- 任务 Kanban、详情、提交、审核、空状态和窄屏行为。
- 组织导入和错误结果展示。
- 原有数字员工、知识库、技能、SOP、工具和渠道页面回归。

### 端到端验收场景

1. 管理员创建部门和三个真人账号。
2. 创建项目并输入目标。
3. 生成三套方案、查看分配理由并选择一套下发。
4. 两位员工分别登录，领取并推进自己的任务。
5. 后续任务在依赖完成后自动解锁。
6. 员工提交成果，经理退回一次，再次提交后通过。
7. CEO 驾驶舱的进度、风险、待审核和动态与上述操作一致。
8. 员工调用绑定的数字员工/知识库能力，但任务责任人与审计主体仍为真人。

## 11. 实施切片

为控制风险，代码按可独立验证的切片交付，但在本轮形成同一个可运行版本：

1. 数据模型、schema、权限与组织 API。
2. 项目、任务、事件和状态机 API。
3. 规划器、人员匹配、三方案和幂等下发。
4. 企业工作台壳层、导航与共享 API 类型。
5. 驾驶舱、调度、任务、员工和组织页面。
6. 种子数据、端到端回归、构建与本地部署验证。
