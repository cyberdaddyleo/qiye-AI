import { describe, expect, it } from 'vitest';

import { businessDateKey, isTaskOverdue } from './workbenchDate';

describe('workbench business dates', () => {
  it('uses local year-month-day parts at the Shanghai 00:30 boundary', () => {
    const now = new Date('2026-09-04T16:30:00.000Z');

    expect(businessDateKey({ now, timeZone: 'Asia/Shanghai' })).toBe('2026-09-05');
    expect(businessDateKey({ now, timeZone: 'UTC' })).toBe('2026-09-04');
    expect(isTaskOverdue('2026-09-04', 'in_progress', {
      now,
      timeZone: 'Asia/Shanghai',
    })).toBe(true);
    expect(isTaskOverdue('2026-09-04', 'in_progress', { now, timeZone: 'UTC' })).toBe(false);
  });

  it('never reports done, canceled, missing, or same-day due dates as overdue', () => {
    const options = {
      now: new Date('2026-09-05T04:00:00.000Z'),
      timeZone: 'Asia/Shanghai',
    };

    expect(isTaskOverdue('2026-09-04', 'done', options)).toBe(false);
    expect(isTaskOverdue('2026-09-04', 'canceled', options)).toBe(false);
    expect(isTaskOverdue(null, 'in_progress', options)).toBe(false);
    expect(isTaskOverdue('2026-09-05', 'in_progress', options)).toBe(false);
  });
});
