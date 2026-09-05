import type { WorkTaskEventRead } from '@/types/workbench';

const EVENT_ACTION: Record<string, string> = {
  task_created: '创建了任务',
  task_assigned: '分配了真人负责人',
  task_started: '开始了任务',
  task_updated: '更新了任务',
  progress_updated: '更新了进度',
  comment_added: '添加了评论',
  result_submitted: '提交了成果',
  review_approved: '通过了任务',
  review_returned: '退回了任务',
  task_unblocked: '解除了阻塞',
  dependency_unblocked: '因依赖完成自动解锁了任务',
  dependencies_updated: '更新了依赖',
  task_canceled: '取消了任务',
  plan_dispatched: '下发了执行方案',
};

export function formatWorkbenchEvent(
  event: WorkTaskEventRead,
  actorName: string,
  fallback = '更新了工作动态',
): string {
  return `${actorName}${EVENT_ACTION[event.event_type] || fallback}`;
}

export function eventDetail(event: WorkTaskEventRead): string | null {
  const value = event.payload.comment ?? event.payload.result_summary;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export function latestArtifactRefs(events: WorkTaskEventRead[]): string[] {
  const latest = [...events]
    .filter((event) => event.event_type === 'result_submitted')
    .sort((left, right) => (
      right.created_at.localeCompare(left.created_at) || right.id.localeCompare(left.id)
    ))[0];
  const values = latest?.payload.artifact_refs;
  if (!Array.isArray(values)) return [];
  return [...new Set(values.flatMap((value) => (
    typeof value === 'string' && value.trim() ? [value.trim()] : []
  )))];
}
