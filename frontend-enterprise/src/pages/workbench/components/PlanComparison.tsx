import { CalendarClock, CircleAlert, Coins, Gauge, Route, UsersRound } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type {
  EmployeeRead,
  PlanningTask,
  PlanVariant,
  PlanVariantKey,
} from '@/types/workbench';

import EmployeeBadgeContainer from './EmployeeBadgeContainer';
import WorkloadBar from './WorkloadBar';

export type PlanComparisonProps = {
  variants: PlanVariant[];
  employees: EmployeeRead[];
  selectedVariantKey: PlanVariantKey;
  editedVariantKeys?: PlanVariantKey[];
  onSelectVariant: (key: PlanVariantKey) => void;
  onUpdateTask: (
    variantKey: PlanVariantKey,
    taskKey: string,
    values: Partial<PlanningTask>,
  ) => void;
};

const STRATEGY_LABEL: Record<PlanVariant['strategy'], string> = {
  balanced: '均衡推进',
  fast: '快速交付',
  cost: '成本优先',
};

function formatCurrency(value: unknown): string {
  const amount = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(amount)}`;
}

function metric(value: unknown, fallback = '待计算'): string {
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'string' && value) return value;
  return fallback;
}

export default function PlanComparison({
  variants,
  employees,
  selectedVariantKey,
  editedVariantKeys = [],
  onSelectVariant,
  onUpdateTask,
}: PlanComparisonProps) {
  const employeeByUserId = new Map(employees.map((employee) => [employee.user_id, employee]));
  const selectedVariant = variants.find((variant) => variant.key === selectedVariantKey)
    || variants[0];

  if (!selectedVariant) return null;

  const taskTitleByKey = new Map(
    selectedVariant.tasks.map((task) => [task.key, task.title]),
  );
  const unassignedCount = selectedVariant.tasks.filter((task) => !task.assignee_user_id).length;

  return (
    <div className="space-y-[18px]">
      <section className="grid grid-cols-1 gap-[14px] xl:grid-cols-3" aria-label="规划方案比较">
        {variants.map((variant) => {
          const selected = variant.key === selectedVariantKey;
          const titleByKey = new Map(variant.tasks.map((task) => [task.key, task.title]));
          const criticalPath = Array.isArray(variant.metrics.critical_path)
            ? variant.metrics.critical_path.map((key) => titleByKey.get(key) || key).join(' → ')
            : '待计算';
          const peakUtilization = Object.values(variant.utilization).reduce(
            (highest, row) => Math.max(highest, row.utilization_percent || 0),
            0,
          );

          return (
            <article
              key={variant.key}
              aria-label={`${variant.key} 方案`}
              className={`min-w-0 rounded-[16px] border bg-white p-[18px] shadow-[0_8px_24px_rgba(24,30,46,0.035)] ${
                selected ? 'border-[#1a71ff] ring-2 ring-[#1a71ff]/10' : 'border-[#edf0f5]'
              }`}
            >
              <div className="flex items-start justify-between gap-[12px]">
                <div>
                  <p className="m-0 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#1a71ff]">
                    方案 {variant.key}
                  </p>
                  <h3 className="mt-[5px] mb-0 text-[15px] font-semibold text-[#24262d]">
                    {variant.name || STRATEGY_LABEL[variant.strategy]}
                  </h3>
                  <p className="mt-[4px] mb-0 text-[11px] text-[#858b9c]">
                    {STRATEGY_LABEL[variant.strategy]}
                  </p>
                  {editedVariantKeys.includes(variant.key) && (
                    <p className="mt-[4px] mb-0 text-[9px] font-medium text-[#a65f00]">
                      AI 原始方案估算
                    </p>
                  )}
                </div>
                <Button
                  type="button"
                  variant={selected ? 'default' : 'outline'}
                  aria-pressed={selected}
                  onClick={() => onSelectVariant(variant.key)}
                  className={selected
                    ? 'h-[30px] rounded-[9px] bg-[#18181a] px-[11px] text-[11px] text-white hover:bg-[#303030]'
                    : 'h-[30px] rounded-[9px] border-[#e3e7f1] px-[11px] text-[11px] text-[#596176]'}
                >
                  选择 {variant.key} 方案
                </Button>
              </div>

              <dl className="mt-[16px] grid grid-cols-2 gap-[10px] text-[11px]">
                <Metric icon={<Coins />} label="预计成本" value={formatCurrency(variant.metrics.cost)} />
                <Metric icon={<CalendarClock />} label="预计完成" value={metric(variant.metrics.finish_date)} />
                <Metric icon={<Gauge />} label="峰值利用率" value={`${Math.round(peakUtilization)}%`} />
                <Metric icon={<UsersRound />} label="峰值并发" value={`${metric(variant.metrics.peak_parallelism, '0')} 人`} />
              </dl>

              <div className="mt-[14px] rounded-[11px] bg-[#f7f9fc] px-[12px] py-[10px]">
                <p className="m-0 flex items-center gap-[6px] text-[10px] font-medium text-[#757f9c]">
                  <Route className="size-[12px]" aria-hidden="true" />
                  关键路径
                </p>
                <p className="mt-[5px] mb-0 text-[11px] leading-[17px] text-[#464c5e]">{criticalPath}</p>
              </div>

              <div className="mt-[12px] space-y-[7px]">
                {Object.entries(variant.utilization).map(([userId, row]) => (
                  <WorkloadBar
                    key={userId}
                    compact
                    value={row.utilization_percent}
                    label={`${employeeByUserId.get(userId)?.display_name || employeeByUserId.get(userId)?.username || '真人员工'}利用率`}
                    detail={employeeByUserId.get(userId)?.display_name || employeeByUserId.get(userId)?.username || '真人员工信息受限'}
                  />
                ))}
              </div>

              <div className="mt-[12px] space-y-[5px]">
                {(variant.risks.length ? variant.risks : ['暂未识别显著风险']).map((risk) => (
                  <p key={risk} className="m-0 flex gap-[6px] text-[10px] leading-[16px] text-[#a65f00]">
                    <CircleAlert className="mt-[2px] size-[11px] shrink-0" aria-hidden="true" />
                    {risk}
                  </p>
                ))}
              </div>
            </article>
          );
        })}
      </section>

      <section
        role="region"
        aria-label="可编辑 WBS"
        className="rounded-[16px] border border-[#edf0f5] bg-white p-[20px] shadow-[0_8px_24px_rgba(24,30,46,0.035)]"
      >
        <div className="flex flex-wrap items-start justify-between gap-[12px]">
          <div>
            <h3 className="m-0 text-[15px] font-semibold text-[#24262d]">可编辑 WBS · 方案 {selectedVariant.key}</h3>
            <p className="mt-[5px] mb-0 text-[11px] leading-[18px] text-[#858b9c]">
              AI 仅提供拆解和匹配建议；负责人均为真人员工，最终安排由你确认。
            </p>
          </div>
          {unassignedCount > 0 && (
            <p className="m-0 rounded-[9px] bg-[#fff4dd] px-[10px] py-[6px] text-[11px] font-medium text-[#a65f00]">
              {unassignedCount} 项任务待人工指派
            </p>
          )}
          {editedVariantKeys.includes(selectedVariant.key) && (
            <p className="m-0 rounded-[9px] bg-[#fff4dd] px-[10px] py-[6px] text-[11px] font-medium text-[#a65f00]">
              WBS 已修改，估算未重新计算
            </p>
          )}
        </div>

        <div className="mt-[16px] space-y-[12px]">
          {selectedVariant.tasks.map((task, index) => {
            const assignee = task.assignee_user_id
              ? employeeByUserId.get(task.assignee_user_id)
              : undefined;
            const manualAssignment = task.assignment.provenance === 'manual';
            const manualAssignmentLabel = task.assignment.manual_assignment_kind === 'reassigned'
              ? '人工改派'
              : '人工指定';
            return (
              <article key={task.key} className="rounded-[13px] border border-[#edf0f5] bg-[#fbfcfe] p-[16px]">
                <div className="flex flex-wrap items-start justify-between gap-[10px]">
                  <div className="min-w-0">
                    <p className="m-0 text-[10px] font-semibold tracking-[0.06em] text-[#9aa1b3]">
                      WBS {String(index + 1).padStart(2, '0')} · {task.required_role || '待确定岗位'}
                    </p>
                    <h4 className="mt-[4px] mb-0 text-[14px] font-semibold text-[#24262d]">{task.title}</h4>
                    <p className="mt-[5px] mb-0 text-[11px] leading-[18px] text-[#596176]">{task.description}</p>
                  </div>
                  <span className="rounded-full bg-[#eef4ff] px-[8px] py-[4px] text-[10px] text-[#1a71ff]">
                    {task.estimate_days} 人日
                  </span>
                </div>

                <div className="mt-[14px] grid gap-[12px] md:grid-cols-2 xl:grid-cols-4">
                  <label className="grid gap-[6px] xl:col-span-2">
                    <span className="text-[11px] font-medium text-[#596176]">真人负责人</span>
                    <select
                      aria-label={`${task.title}负责人`}
                      value={task.assignee_user_id || ''}
                      onChange={(event) => onUpdateTask(selectedVariant.key, task.key, {
                        assignee_user_id: event.target.value || null,
                      })}
                      className="h-[34px] w-full rounded-[9px] border border-[#e3e7f1] bg-white px-[10px] text-[12px] text-[#464c5e] outline-none focus:border-[#18181a]"
                    >
                      <option value="">待人工指派</option>
                      {task.assignee_user_id && !assignee && (
                        <option value={task.assignee_user_id}>当前真人负责人 · 目录信息受限</option>
                      )}
                      {employees.filter((row) => row.status === 'active').map((row) => (
                        <option key={row.user_id} value={row.user_id}>
                          {row.display_name || row.username} · {row.job_title || '真人员工'}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="grid gap-[6px]">
                    <span className="text-[11px] font-medium text-[#596176]">开始日期</span>
                    <Input
                      type="date"
                      aria-label={`${task.title}开始日期`}
                      value={task.start_date || ''}
                      onChange={(event) => onUpdateTask(selectedVariant.key, task.key, {
                        start_date: event.target.value || null,
                      })}
                      className="h-[34px] rounded-[9px] border-[#e3e7f1] bg-white text-[12px]"
                    />
                  </label>
                  <label className="grid gap-[6px]">
                    <span className="text-[11px] font-medium text-[#596176]">截止日期</span>
                    <Input
                      type="date"
                      aria-label={`${task.title}截止日期`}
                      value={task.due_date || ''}
                      onChange={(event) => onUpdateTask(selectedVariant.key, task.key, {
                        due_date: event.target.value || null,
                      })}
                      className="h-[34px] rounded-[9px] border-[#e3e7f1] bg-white text-[12px]"
                    />
                  </label>
                </div>

                <label className="mt-[12px] grid gap-[6px]">
                  <span className="text-[11px] font-medium text-[#596176]">验收标准</span>
                  <Textarea
                    aria-label={`${task.title}验收标准`}
                    value={task.acceptance_criteria}
                    onChange={(event) => onUpdateTask(selectedVariant.key, task.key, {
                      acceptance_criteria: event.target.value,
                    })}
                    className="min-h-[66px] rounded-[9px] border-[#e3e7f1] bg-white text-[12px]"
                  />
                </label>

                {selectedVariant.tasks.length > 1 && (
                  <fieldset className="mt-[12px] rounded-[10px] border border-[#edf0f5] bg-white px-[12px] py-[9px]">
                    <legend className="px-[4px] text-[10px] font-medium text-[#858b9c]">前置依赖</legend>
                    <div className="flex flex-wrap gap-x-[14px] gap-y-[7px]">
                      {selectedVariant.tasks.filter((candidate) => candidate.key !== task.key).map((candidate) => {
                        const checked = task.depends_on.includes(candidate.key);
                        return (
                          <label key={candidate.key} className="flex items-center gap-[6px] text-[11px] text-[#596176]">
                            <input
                              type="checkbox"
                              aria-label={`${task.title}依赖${candidate.title}`}
                              checked={checked}
                              onChange={(event) => onUpdateTask(selectedVariant.key, task.key, {
                                depends_on: event.target.checked
                                  ? [...task.depends_on, candidate.key]
                                  : task.depends_on.filter((key) => key !== candidate.key),
                              })}
                              className="size-[14px] accent-[#1a71ff]"
                            />
                            {candidate.title}
                          </label>
                        );
                      })}
                    </div>
                  </fieldset>
                )}

                <div className="mt-[12px] rounded-[10px] bg-white px-[12px] py-[9px]">
                  {assignee ? (
                    <div className="grid gap-[9px] md:grid-cols-[minmax(0,190px)_1fr] md:items-center">
                      <EmployeeBadgeContainer employee={assignee} compact subtitle="真人任务负责人" />
                      <p className="m-0 text-[10px] leading-[17px] text-[#757f9c]">
                        {manualAssignment ? (
                          <span className="font-medium text-[#596176]">{manualAssignmentLabel}</span>
                        ) : (
                          <>
                            <span className="font-medium text-[#596176]">AI 推荐理由：</span>
                            {task.assignment.rationale || '此负责人来自 AI 原始方案推荐。'}
                          </>
                        )}
                      </p>
                    </div>
                  ) : task.assignee_user_id ? (
                    <p className="m-0 text-[10px] font-medium leading-[17px] text-[#596176]">
                      已指派（员工目录信息受限）
                    </p>
                  ) : (
                    <p className="m-0 flex items-start gap-[6px] text-[10px] leading-[17px] text-[#a65f00]">
                      <CircleAlert className="mt-[2px] size-[11px] shrink-0" aria-hidden="true" />
                      {task.unassigned_reason || '暂无合适员工，请由管理者人工指派。'}
                    </p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-[10px] border border-[#f0f2f6] px-[10px] py-[9px]">
      <dt className="flex items-center gap-[5px] text-[9px] text-[#9aa1b3] [&_svg]:size-[11px]" aria-label={label}>
        {icon}
        {label}
      </dt>
      <dd className="mt-[5px] mb-0 text-[11px] font-semibold text-[#464c5e]">{value}</dd>
    </div>
  );
}
