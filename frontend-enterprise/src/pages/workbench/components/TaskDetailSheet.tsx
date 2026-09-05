import { useEffect, useMemo, useState } from 'react';
import {
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Clock3,
  GitBranch,
  Link2,
  MessageSquareText,
  Play,
  Plus,
  RotateCcw,
  Send,
  X,
} from 'lucide-react';

import type { EnterpriseAuthUser } from '@/auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { formatDateTime } from '@/lib/enterprise-ui';
import type {
  EmployeeRead,
  ProjectRead,
  ReviewVerdict,
  TaskRead,
  WorkbenchAccessRead,
} from '@/types/workbench';

import { eventDetail, formatWorkbenchEvent, latestArtifactRefs } from '../workbenchEvents';
import { taskStatusLabel, taskStatusTone } from '../workbenchModel';
import EmployeeBadgeContainer from './EmployeeBadgeContainer';

export type TaskDetailSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  task: TaskRead | null;
  loading?: boolean;
  error?: unknown;
  actionError?: string;
  conflictMessage?: string;
  busy?: boolean;
  currentUser: EnterpriseAuthUser;
  access: WorkbenchAccessRead | null;
  employees: EmployeeRead[];
  projects: ProjectRead[];
  allTasks: TaskRead[];
  onRetry?: () => void;
  onOpenTask?: (taskId: string) => void;
  onStart: () => Promise<boolean> | boolean;
  onProgress: (progress: number) => Promise<boolean> | boolean;
  onComment: (comment: string) => Promise<boolean> | boolean;
  onSubmit: (summary: string, artifactRefs: string[]) => Promise<boolean> | boolean;
  onReview: (verdict: ReviewVerdict, comment: string) => Promise<boolean> | boolean;
};

const STATUS_CLASS = {
  blue: 'bg-[#eaf2ff] text-[#1a71ff]',
  orange: 'bg-[#fff4dd] text-[#a65f00]',
  green: 'bg-[#e9f7ef] text-[#018434]',
  red: 'bg-[#fce7e7] text-[#d20b0b]',
  gray: 'bg-[#f2f3f7] text-[#596176]',
};

const PRIORITY_LABEL: Record<TaskRead['priority'], string> = {
  low: '低优先级',
  normal: '普通',
  high: '高优先级',
  urgent: '紧急',
};

export default function TaskDetailSheet({
  open,
  onOpenChange,
  task,
  loading = false,
  error,
  actionError,
  conflictMessage,
  busy = false,
  currentUser,
  access,
  employees,
  projects,
  allTasks,
  onRetry,
  onOpenTask,
  onStart,
  onProgress,
  onComment,
  onSubmit,
  onReview,
}: TaskDetailSheetProps) {
  const [comment, setComment] = useState('');
  const [summary, setSummary] = useState('');
  const [progress, setProgress] = useState('0');
  const [artifactRefs, setArtifactRefs] = useState<string[]>(['']);
  const [reviewComment, setReviewComment] = useState('');
  const [formError, setFormError] = useState('');

  useEffect(() => {
    setComment('');
    setSummary(task?.result_summary || '');
    const existingRefs = latestArtifactRefs(task?.events || []);
    setArtifactRefs(existingRefs.length ? existingRefs : ['']);
    setReviewComment('');
    setFormError('');
  }, [task?.id]);

  useEffect(() => {
    setProgress(String(task?.progress ?? 0));
  }, [task?.id, task?.progress]);

  const employeeByUserId = useMemo(
    () => new Map(employees.map((employee) => [employee.user_id, employee])),
    [employees],
  );
  const assignee = task?.assignee_user_id
    ? employeeByUserId.get(task.assignee_user_id)
    : undefined;
  const reviewer = task?.reviewer_user_id
    ? employeeByUserId.get(task.reviewer_user_id)
    : undefined;
  const taskById = useMemo(() => new Map(allTasks.map((row) => [row.id, row])), [allTasks]);
  const project = task ? projects.find((row) => row.id === task.project_id) : undefined;
  const projectOwner = project?.owner_user_id === currentUser.id;
  const managedProject = Boolean(
    project?.department_id
    && access?.managed_department_ids.includes(project.department_id),
  );
  const canManageProject = Boolean(access?.can_view_all || projectOwner || managedProject);
  const canExecute = Boolean(task && (
    task.assignee_user_id === currentUser.id || canManageProject
  ));
  const canReview = Boolean(task && (
    task.reviewer_user_id === currentUser.id || canManageProject
  ));
  const events = useMemo(
    () => [...(task?.events || [])].sort((left, right) => (
      left.created_at.localeCompare(right.created_at) || left.id.localeCompare(right.id)
    )),
    [task?.events],
  );
  const latestReviewerComment = [...events].reverse().find((event) => (
    (event.event_type === 'review_returned' || event.event_type === 'review_approved')
    && eventDetail(event)
  ));
  const submittedArtifactRefs = latestArtifactRefs(events);
  const isResubmission = Boolean(task?.result_summary || submittedArtifactRefs.length);

  async function submitComment() {
    const value = comment.trim();
    if (!value) {
      setFormError('请输入评论内容。');
      return;
    }
    setFormError('');
    if (await onComment(value)) setComment('');
  }

  async function submitResult() {
    const value = summary.trim();
    if (!value) {
      setFormError('请输入成果摘要。');
      return;
    }
    const refs = [...new Set(artifactRefs.map((reference) => reference.trim()).filter(Boolean))];
    if (!refs.length) {
      setFormError('请至少填写一个成果引用（URL 或资源 ID）。');
      return;
    }
    setFormError('');
    if (await onSubmit(value, refs)) {
      setSummary('');
      setArtifactRefs(['']);
    }
  }

  async function submitProgress() {
    const value = Number(progress);
    if (!Number.isInteger(value) || value < 0 || value > 100) {
      setFormError('任务进度必须是 0 到 100 的整数。');
      return;
    }
    setFormError('');
    await onProgress(value);
  }

  function changeArtifactRef(index: number, value: string) {
    setArtifactRefs((current) => current.map((reference, currentIndex) => (
      currentIndex === index ? value : reference
    )));
  }

  function removeArtifactRef(index: number) {
    setArtifactRefs((current) => {
      const next = current.filter((_, currentIndex) => currentIndex !== index);
      return next.length ? next : [''];
    });
  }

  async function review(verdict: ReviewVerdict) {
    const value = reviewComment.trim();
    if (verdict === 'rework' && !value) {
      setFormError('退回重做时请填写审核意见。');
      return;
    }
    setFormError('');
    if (await onReview(verdict, value)) setReviewComment('');
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[min(680px,92vw)] max-w-[680px] gap-0 overflow-hidden border-l border-[#e3e7f1] bg-[#f7f9fc] p-0 data-[side=right]:sm:max-w-[680px] data-[side=right]:max-[640px]:w-full max-[640px]:max-w-none"
      >
        <SheetHeader className="border-b border-[#e8ebf2] bg-white px-[22px] py-[18px] pr-[54px]">
          <SheetTitle className="text-[16px] font-semibold text-[#24262d]">
            {task?.title || '任务详情'}
          </SheetTitle>
          <SheetDescription className="mt-[5px] text-[11px] leading-[18px] text-[#858b9c]">
            {project?.name || '查看任务责任、依赖、交付与审核记录'}
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-[18px] py-[16px]">
          {loading ? (
            <div role="status" aria-label="任务详情加载中" className="space-y-[10px]">
              {Array.from({ length: 4 }, (_, index) => <div key={index} className="h-[92px] animate-pulse rounded-[13px] bg-[#e9edf4]" />)}
            </div>
          ) : error ? (
            <section role="alert" className="rounded-[14px] border border-[#f1d4d4] bg-white px-[20px] py-[32px] text-center">
              <CircleAlert className="mx-auto size-[25px] text-[#d20b0b]" aria-hidden="true" />
              <h3 className="mt-[10px] mb-0 text-[14px] font-semibold text-[#24262d]">
                {error instanceof Error && 'status' in error && error.status === 403 ? '无权查看此任务' : '任务详情加载失败'}
              </h3>
              {onRetry && <Button type="button" onClick={onRetry} className="mt-[14px] h-[32px] rounded-[9px] bg-[#18181a] px-[14px] text-[11px] text-white">重试</Button>}
            </section>
          ) : task ? (
            <div className="space-y-[13px]">
              {conflictMessage && <p role="alert" className="m-0 rounded-[10px] bg-[#fff4dd] px-[12px] py-[9px] text-[11px] leading-[18px] text-[#a65f00]">{conflictMessage}</p>}
              {actionError && <p role="alert" className="m-0 rounded-[10px] bg-[#fce7e7] px-[12px] py-[9px] text-[11px] leading-[18px] text-[#d20b0b]">{actionError}</p>}
              {formError && <p role="alert" className="m-0 rounded-[10px] bg-[#fff4dd] px-[12px] py-[9px] text-[11px] leading-[18px] text-[#a65f00]">{formError}</p>}

              <section className="rounded-[14px] border border-[#edf0f5] bg-white p-[15px]">
                <div className="flex flex-wrap items-center gap-[7px]">
                  <span className={`rounded-full px-[8px] py-[4px] text-[10px] font-medium ${STATUS_CLASS[taskStatusTone(task.status)]}`}>
                    {taskStatusLabel(task.status)}
                  </span>
                  <span className="rounded-full bg-[#f2f3f7] px-[8px] py-[4px] text-[10px] text-[#596176]">{PRIORITY_LABEL[task.priority]}</span>
                  <span className="text-[10px] text-[#9aa1b3]">版本 {task.version}</span>
                </div>
                {task.description && <p className="mt-[10px] mb-0 whitespace-pre-wrap text-[12px] leading-[20px] text-[#596176]">{task.description}</p>}
                <dl className="mt-[13px] grid grid-cols-2 gap-[9px] border-t border-[#f0f2f6] pt-[12px] text-[10px]">
                  <Info icon={<CalendarDays />} label="任务周期" value={`${task.start_date || '待定'} 至 ${task.due_date || '待定'}`} />
                  <Info icon={<Clock3 />} label="预计工期" value={task.estimate_days == null ? '待定' : `${task.estimate_days} 人日`} />
                </dl>
              </section>

              <section className="grid gap-[10px] rounded-[14px] border border-[#edf0f5] bg-white p-[15px] sm:grid-cols-2">
                <div>
                  <p className="mt-0 mb-[8px] text-[10px] font-medium text-[#858b9c]">真人负责人</p>
                  <EmployeeBadgeContainer employee={assignee} name={task.assignee_user_id && !assignee ? '负责人信息受限' : undefined} compact subtitle="任务责任人" />
                </div>
                <div>
                  <p className="mt-0 mb-[8px] text-[10px] font-medium text-[#858b9c]">真人审核人</p>
                  <EmployeeBadgeContainer employee={reviewer} name={task.reviewer_user_id && !reviewer ? '审核人信息受限' : undefined} compact subtitle="成果审核人" />
                </div>
              </section>

              <section className="rounded-[14px] border border-[#edf0f5] bg-white p-[15px]">
                <h3 className="m-0 text-[12px] font-semibold text-[#464c5e]">依赖与验收</h3>
                <div className="mt-[10px]">
                  <p className="m-0 flex items-center gap-[5px] text-[10px] font-medium text-[#858b9c]"><GitBranch className="size-[11px]" aria-hidden="true" />前置依赖</p>
                  {task.dependencies.length ? (
                    <div className="mt-[7px] flex flex-wrap gap-[6px]">
                      {task.dependencies.map((dependencyId) => {
                        const dependency = taskById.get(dependencyId);
                        const label = dependency?.title || dependencyId;
                        return (
                          <Button key={dependencyId} type="button" variant="outline" aria-label={`查看依赖 ${label}`} onClick={() => onOpenTask?.(dependencyId)} className="h-[29px] rounded-[8px] border-[#e3e7f1] px-[9px] text-[10px] text-[#596176]">
                            {label} · {dependency ? taskStatusLabel(dependency.status) : '查看'}
                          </Button>
                        );
                      })}
                    </div>
                  ) : <p className="mt-[6px] mb-0 text-[11px] text-[#9aa1b3]">无前置依赖</p>}
                </div>
                <div className="mt-[12px] border-t border-[#f0f2f6] pt-[11px]">
                  <p className="m-0 text-[10px] font-medium text-[#858b9c]">验收标准</p>
                  <p className="mt-[6px] mb-0 whitespace-pre-wrap text-[11px] leading-[18px] text-[#596176]">{task.acceptance_criteria || '尚未设置验收标准'}</p>
                </div>
              </section>

              {(task.result_summary || submittedArtifactRefs.length || latestReviewerComment) && (
                <section className="rounded-[14px] border border-[#edf0f5] bg-white p-[15px]">
                  <h3 className="m-0 text-[12px] font-semibold text-[#464c5e]">成果与审核</h3>
                  {task.result_summary && <div className="mt-[10px]"><p className="m-0 text-[10px] font-medium text-[#858b9c]">成果摘要</p><p className="mt-[5px] mb-0 whitespace-pre-wrap text-[11px] leading-[18px] text-[#596176]">{task.result_summary}</p></div>}
                  {submittedArtifactRefs.length > 0 && (
                    <div className="mt-[10px] border-t border-[#f0f2f6] pt-[10px]">
                      <p className="m-0 text-[10px] font-medium text-[#858b9c]">成果引用</p>
                      <ul className="mt-[6px] mb-0 grid gap-[5px] p-0">
                        {submittedArtifactRefs.map((reference) => {
                          const url = safeArtifactUrl(reference);
                          return (
                            <li key={reference} className="flex min-w-0 list-none items-center gap-[5px] text-[10px] text-[#596176]">
                              <Link2 className="size-[11px] shrink-0" aria-hidden="true" />
                              {url ? <a href={url} target="_blank" rel="noreferrer" className="min-w-0 truncate text-[#1a71ff] hover:underline" data-i18n-ignore>{reference}</a> : <span className="min-w-0 break-all font-mono" data-i18n-ignore>{reference}</span>}
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  )}
                  {latestReviewerComment && <div className="mt-[10px] border-t border-[#f0f2f6] pt-[10px]"><p className="m-0 text-[10px] font-medium text-[#858b9c]">审核意见</p><p className="mt-[5px] mb-0 whitespace-pre-wrap text-[11px] leading-[18px] text-[#596176]">{eventDetail(latestReviewerComment)}</p></div>}
                </section>
              )}

              {(task.status === 'backlog' || task.status === 'blocked') && canExecute && (
                <section className="rounded-[14px] border border-[#edf0f5] bg-white p-[15px]">
                  <Button type="button" disabled={busy || task.status === 'blocked'} onClick={() => void onStart()} className="h-[34px] w-full gap-[6px] rounded-[9px] bg-[#18181a] text-[11px] text-white hover:bg-[#303030]">
                    <Play className="size-[13px]" aria-hidden="true" />
                    开始任务
                  </Button>
                  {task.status === 'blocked' && <p className="mt-[8px] mb-0 text-center text-[10px] text-[#a65f00]">依赖任务完成后才能开始</p>}
                </section>
              )}

              <section className="rounded-[14px] border border-[#edf0f5] bg-white p-[15px]">
                <label className="grid gap-[6px]">
                  <span className="flex items-center gap-[5px] text-[11px] font-medium text-[#596176]"><MessageSquareText className="size-[12px]" aria-hidden="true" />添加评论</span>
                  <Textarea value={comment} onChange={(event) => setComment(event.target.value)} className="min-h-[68px] rounded-[9px] border-[#e3e7f1] text-[11px]" />
                </label>
                <div className="mt-[8px] flex justify-end">
                  <Button type="button" disabled={busy || !comment.trim()} onClick={() => void submitComment()} className="h-[31px] gap-[5px] rounded-[8px] bg-[#18181a] px-[12px] text-[10px] text-white hover:bg-[#303030]"><Send className="size-[11px]" aria-hidden="true" />发表评论</Button>
                </div>
              </section>

              {task.status === 'in_progress' && canExecute && (
                <section className="rounded-[14px] border border-[#dfe6f2] bg-white p-[15px]">
                  <div className="grid gap-[7px] rounded-[10px] bg-[#f7f9fc] p-[10px] sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
                    <label className="grid gap-[5px]">
                      <span className="text-[11px] font-medium text-[#596176]">任务进度</span>
                      <span className="flex items-center gap-[8px]"><Input aria-label="任务进度" type="number" min="0" max="100" step="1" value={progress} onChange={(event) => setProgress(event.target.value)} className="h-[33px] min-w-0 rounded-[8px] border-[#e3e7f1] text-[11px]" /><span className="shrink-0 text-[10px] text-[#858b9c]">%</span></span>
                    </label>
                    <Button type="button" variant="outline" disabled={busy || !progress || Number(progress) === task.progress} onClick={() => void submitProgress()} className="h-[33px] rounded-[8px] border-[#dce2ec] px-[12px] text-[10px] text-[#596176]">保存进度</Button>
                  </div>
                  <label className="grid gap-[6px]">
                    <span className="mt-[11px] text-[11px] font-medium text-[#596176]">成果摘要</span>
                    <Textarea value={summary} onChange={(event) => setSummary(event.target.value)} className="min-h-[82px] rounded-[9px] border-[#e3e7f1] text-[11px]" />
                  </label>
                  <div className="mt-[10px] grid gap-[7px]">
                    <div className="flex items-center justify-between gap-[8px]">
                      <span className="text-[11px] font-medium text-[#596176]">成果引用</span>
                      <Button type="button" variant="ghost" disabled={busy || artifactRefs.length >= 100} onClick={() => setArtifactRefs((current) => [...current, ''])} className="h-[27px] gap-[4px] rounded-[7px] px-[7px] text-[9px] text-[#1a71ff]"><Plus className="size-[10px]" aria-hidden="true" />添加成果引用</Button>
                    </div>
                    {artifactRefs.map((reference, index) => (
                      <div key={index} className="flex items-end gap-[6px]">
                        <label className="grid min-w-0 flex-1 gap-[4px]">
                          <span className="sr-only">成果引用 {index + 1}</span>
                          <Input aria-label={`成果引用 ${index + 1}`} value={reference} onChange={(event) => changeArtifactRef(index, event.target.value)} placeholder="https://… 或资源 ID" className="h-[33px] rounded-[8px] border-[#e3e7f1] text-[11px]" />
                        </label>
                        {artifactRefs.length > 1 && <Button type="button" variant="ghost" aria-label={`移除成果引用 ${index + 1}`} disabled={busy} onClick={() => removeArtifactRef(index)} className="size-[33px] rounded-[8px] p-0 text-[#9aa1b3]"><X className="size-[12px]" aria-hidden="true" /></Button>}
                      </div>
                    ))}
                    <p className="m-0 text-[9px] leading-[15px] text-[#9aa1b3]">可填写文档 URL、知识库资源 ID 或其他可审计成果标识。</p>
                  </div>
                  <Button type="button" disabled={busy || !summary.trim() || !artifactRefs.some((reference) => reference.trim())} onClick={() => void submitResult()} className="mt-[9px] h-[33px] w-full gap-[5px] rounded-[9px] bg-[#1a71ff] text-[11px] text-white hover:bg-[#0f5ed7]"><Send className="size-[12px]" aria-hidden="true" />{isResubmission ? '重新提交成果' : '提交成果'}</Button>
                </section>
              )}

              {task.status === 'review' && canReview && (
                <section className="rounded-[14px] border border-[#f0dfbd] bg-white p-[15px]">
                  <label className="grid gap-[6px]">
                    <span className="text-[11px] font-medium text-[#596176]">审核意见</span>
                    <Textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} className="min-h-[72px] rounded-[9px] border-[#e3e7f1] text-[11px]" />
                  </label>
                  <div className="mt-[9px] grid grid-cols-2 gap-[8px]">
                    <Button type="button" variant="outline" disabled={busy} onClick={() => void review('rework')} className="h-[33px] gap-[5px] rounded-[9px] border-[#efd3d3] text-[11px] text-[#d20b0b]"><RotateCcw className="size-[12px]" aria-hidden="true" />退回重做</Button>
                    <Button type="button" disabled={busy} onClick={() => void review('approve')} className="h-[33px] gap-[5px] rounded-[9px] bg-[#018434] text-[11px] text-white hover:bg-[#016b2b]"><CheckCircle2 className="size-[12px]" aria-hidden="true" />审核通过</Button>
                  </div>
                </section>
              )}

              <section className="rounded-[14px] border border-[#edf0f5] bg-white p-[15px]">
                <h3 className="m-0 text-[12px] font-semibold text-[#464c5e]">协作动态</h3>
                {events.length ? (
                  <ol aria-label="任务动态" className="mt-[11px] mb-0 space-y-[10px] p-0">
                    {events.map((event) => {
                      const actor = event.actor_user_id ? employeeByUserId.get(event.actor_user_id) : undefined;
                      const actorName = actor?.display_name || actor?.username || (event.actor_type === 'system' ? '系统' : '真人成员');
                      const detail = eventDetail(event);
                      return (
                        <li key={event.id} className="list-none border-l-2 border-[#dce5f3] pl-[11px]">
                          <p className="m-0 text-[11px] font-medium text-[#464c5e]">{formatWorkbenchEvent(event, actorName, '更新了任务')}</p>
                          {detail && <p className="mt-[3px] mb-0 whitespace-pre-wrap text-[10px] leading-[16px] text-[#757f9c]">{detail}</p>}
                          <time className="mt-[3px] block text-[9px] text-[#9aa1b3]">{formatDateTime(event.created_at)}</time>
                        </li>
                      );
                    })}
                  </ol>
                ) : <p className="mt-[9px] mb-0 text-[11px] text-[#9aa1b3]">暂无协作动态</p>}
              </section>
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function safeArtifactUrl(reference: string): string | null {
  try {
    const url = new URL(reference);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
}

function Info({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div>
      <dt className="flex items-center gap-[4px] text-[#9aa1b3] [&_svg]:size-[10px]">{icon}{label}</dt>
      <dd className="mt-[4px] mb-0 text-[#596176]">{value}</dd>
    </div>
  );
}
