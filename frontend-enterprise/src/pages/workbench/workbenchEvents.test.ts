import { describe, expect, it } from 'vitest';

import type { WorkTaskEventRead } from '@/types/workbench';

import {
  eventDetail,
  formatWorkbenchEvent,
  latestArtifactRefs,
} from './workbenchEvents';

function event(
  eventType: string,
  payload: Record<string, unknown> = {},
  createdAt = '2026-09-05T08:00:00Z',
): WorkTaskEventRead {
  return {
    id: `${eventType}-${createdAt}`,
    task_id: 'task-1',
    tenant_id: 'tenant-demo',
    actor_user_id: 'user-1',
    actor_type: 'human',
    event_type: eventType,
    payload,
    created_at: createdAt,
  };
}

describe('workbench event formatting', () => {
  it.each([
    ['comment_added', '林珊添加了评论'],
    ['result_submitted', '林珊提交了成果'],
    ['review_approved', '林珊通过了任务'],
    ['review_returned', '林珊退回了任务'],
    ['dependency_unblocked', '林珊因依赖完成自动解锁了任务'],
  ])('maps the server event %s to a specific activity label', (eventType, expected) => {
    expect(formatWorkbenchEvent(event(eventType), '林珊')).toBe(expected);
  });

  it('uses a stable fallback and extracts human-readable event details', () => {
    expect(formatWorkbenchEvent(event('future_event'), '系统')).toBe('系统更新了工作动态');
    expect(eventDetail(event('comment_added', { comment: '  已补充说明  ' }))).toBe('已补充说明');
    expect(eventDetail(event('result_submitted', { result_summary: '  已交付  ' }))).toBe('已交付');
  });

  it('restores only clean references from the latest result submission', () => {
    const events = [
      event('result_submitted', { artifact_refs: ['old-resource'] }, '2026-09-05T07:00:00Z'),
      event('review_returned', { comment: '补充来源' }, '2026-09-05T08:00:00Z'),
      event('result_submitted', {
        artifact_refs: [' https://example.com/report ', '', 'asset-42', 'asset-42', 123],
      }, '2026-09-05T09:00:00Z'),
    ];

    expect(latestArtifactRefs(events)).toEqual(['https://example.com/report', 'asset-42']);
  });
});
