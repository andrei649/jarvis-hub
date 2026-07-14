import { describe, expect, it } from 'vitest';

import {
  canonicalizeDesktopSteps,
  desktopPlanSignature,
  reduceDesktopOutcome,
  sanitizeDesktopResult,
} from '../operator-contract';

function readStep(query = 'summary') {
  return { action: 'read' as const, args: { query } };
}

function clickStep(name = 'Save') {
  return { action: 'click' as const, args: { name } };
}

describe('canonicalizeDesktopSteps', () => {
  it('canonicalizes every supported action with fixed key order', () => {
    const result = canonicalizeDesktopSteps([
      { action: ' READ ', args: { query: '  account total  ' } },
      { action: 'LOCATE', args: { query: '  Save button ' } },
      { action: ' click ', args: { name: '  Save ' } },
      { action: ' TYPE ', args: { name: '  Password ', text: '  keep exactly  ' } },
      { action: ' Launch ', args: { app: '  NOTEPAD_2  ' } },
    ]);

    expect(result).toEqual([
      { action: 'read', args: { query: 'account total' } },
      { action: 'locate', args: { query: 'Save button' } },
      { action: 'click', args: { name: 'Save' } },
      { action: 'type', args: { name: 'Password', text: '  keep exactly  ' } },
      { action: 'launch', args: { app: 'notepad_2' } },
    ]);
    expect(Object.keys(result[0])).toEqual(['action', 'args']);
    expect(Object.keys(result[3].args)).toEqual(['name', 'text']);
  });

  it('returns a deep new value without mutating its input', () => {
    const source = [{ action: 'click', args: { name: '  Continue  ' } }];
    const before = structuredClone(source);
    const result = canonicalizeDesktopSteps(source);

    expect(source).toEqual(before);
    expect(result).not.toBe(source);
    expect(result[0]).not.toBe(source[0]);
    expect(result[0].args).not.toBe(source[0].args);
  });

  it('produces a stable signature from equivalent normalized inputs', () => {
    const left = [{ args: { name: ' Save ' }, action: ' CLICK ' }];
    const right = [{ action: 'click', args: { name: 'Save' } }];

    expect(desktopPlanSignature(left)).toBe(desktopPlanSignature(right));
    expect(desktopPlanSignature(left)).toBe('[{"action":"click","args":{"name":"Save"}}]');
  });

  it.each([
    ['empty plan', []],
    ['too many steps', Array.from({ length: 21 }, () => ({ action: 'read', args: { query: 'x' } }))],
    ['non-array plan', { action: 'read' }],
    ['unsupported action', [{ action: 'observe', args: {} }]],
    ['missing args', [{ action: 'read' }]],
    ['extra step key', [{ action: 'read', args: { query: 'x' }, raw: true }]],
    ['approval step field', [{ action: 'click', args: { name: 'x' }, approved: true }]],
    ['approval args field', [{ action: 'click', args: { name: 'x', caller_approved: true } }]],
    ['missing action argument', [{ action: 'click', args: {} }]],
    ['extra action argument', [{ action: 'read', args: { query: 'x', name: 'y' } }]],
    ['non-string action', [{ action: 3, args: { query: 'x' } }]],
    ['non-object args', [{ action: 'read', args: 'x' }]],
    ['empty trimmed query', [{ action: 'read', args: { query: '  ' } }]],
    ['query over cap', [{ action: 'read', args: { query: 'q'.repeat(513) } }]],
    ['name over cap', [{ action: 'click', args: { name: 'n'.repeat(513) } }]],
    ['type text over cap', [{ action: 'type', args: { name: 'field', text: 's'.repeat(4001) } }]],
    ['invalid app id', [{ action: 'launch', args: { app: '2bad-app' } }]],
  ])('rejects %s', (_label, value) => {
    expect(() => canonicalizeDesktopSteps(value)).toThrow();
  });

  it('accepts exact query, name, and type-text boundaries', () => {
    expect(canonicalizeDesktopSteps([
      { action: 'read', args: { query: 'q'.repeat(512) } },
      { action: 'type', args: { name: 'n'.repeat(512), text: 's'.repeat(4000) } },
    ])).toHaveLength(2);
  });
});

describe('reduceDesktopOutcome', () => {
  it.each([
    ['preview wins over a hostile failure collision', 'preview', { ok: false, reason: 'injection_detected' }, 1, 'proposed'],
    ['real approval-required response queues', 'run', { ok: false, reason: 'approval_required', task_id: ' task-7 ' }, 1, 'queued'],
    ['boolean approval alias queues', 'run', { ok: false, approval_required: true, task_id: 42 }, 1, 'queued'],
    ['approval without a task id blocks', 'run', { ok: false, reason: 'approval_required' }, 1, 'blocked'],
    ['numeric-only evidence cannot prove execution identity', 'run', { ok: true, ran: [{ action: 'read', status: 'ran' }, { action: 'click', status: 'ran' }] }, 2, 'partial'],
    ['exact verified snapshot actions execute', 'run', { ok: true, ran: [{ action: 'read', status: 'ran' }, { action: 'click', status: 'ran' }] }, [readStep(), clickStep()], 'executed'],
    ['a positive ran count beats a refusal collision', 'run', { ok: false, reason: 'injection_detected', ran: [{ status: 'ran' }] }, 2, 'partial'],
    ['a returned-count mismatch is partial', 'run', { ok: true, ran: [{ status: 'ran' }, { status: 'failed' }] }, 2, 'partial'],
    ['an exact governance refusal blocks', 'run', { ok: false, reason: 'desktop_host_disabled', ran: [] }, 1, 'blocked'],
    ['an unverified host error fails', 'run', { ok: false, reason: 'host_crashed', ran: [] }, 1, 'failed'],
    ['substring lookalikes do not count as refusals', 'run', { ok: false, reason: 'maybe_injection_detected_later', ran: [] }, 1, 'failed'],
  ] as const)('%s', (_label, context, result, submittedCount, expected) => {
    expect(reduceDesktopOutcome(context, result, submittedCount)).toBe(expected);
  });

  it.each([
    [
      '21 returned rows for a 20-step submission',
      {
        ok: true,
        ran: [
          ...Array.from({ length: 20 }, (_, index) => ({ action: index ? 'click' : 'read', status: 'ran' })),
          { action: 'click', status: 'blocked' },
        ],
      },
      20,
    ],
    [
      'an exact ran row only beyond the display cap',
      {
        ok: false,
        ran: [
          ...Array.from({ length: 20 }, (_, index) => ({ action: index ? 'click' : 'read', status: 'failed' })),
          { action: 'click', status: 'ran' },
        ],
      },
      20,
    ],
    ['a missing action', { ok: true, ran: [{ status: 'ran' }] }, 1],
    ['a wrong action', { ok: true, ran: [{ action: 'click', status: 'ran' }] }, 1],
    [
      'actions in the wrong order',
      { ok: true, ran: [{ action: 'click', status: 'ran' }, { action: 'read', status: 'ran' }] },
      2,
    ],
  ])('fails closed as partial for numeric-only anomalous evidence: %s', (_label, result, submittedCount) => {
    expect(reduceDesktopOutcome('run', result, submittedCount)).toBe('partial');
  });

  it.each([
    ['a missing returned action', { ok: true, ran: [{ status: 'ran' }] }, [readStep()]],
    ['a mismatched returned action', { ok: true, ran: [{ action: 'click', status: 'ran' }] }, [readStep()]],
    [
      'returned actions in the wrong order',
      { ok: true, ran: [{ action: 'click', status: 'ran' }, { action: 'read', status: 'ran' }] },
      [readStep(), clickStep()],
    ],
  ])('requires exact submitted snapshot action identity: %s', (_label, result, submittedSteps) => {
    expect(reduceDesktopOutcome('run', result, submittedSteps)).toBe('partial');
  });

  it.each([
    '', '   ', 0, -1, Number.NaN, Number.POSITIVE_INFINITY, {},
  ])('blocks rather than queues with an unusable task id: %s', (taskId) => {
    expect(reduceDesktopOutcome(
      'run',
      { ok: false, approval_required: true, task_id: taskId },
      1,
    )).toBe('blocked');
  });
});

describe('sanitizeDesktopResult', () => {
  it('reconstructs only the bounded safe projection from hostile output', () => {
    const hostileElements = Array.from({ length: 12 }, (_, index) => ({
      role: `role-${index}-${'r'.repeat(140)}`,
      name: `name-${index}-${'n'.repeat(140)}`,
      value: 'secret',
      automation_id: 'private-id',
      path: 'C:\\private',
    }));
    const hostile = {
      ok: false,
      reason: 'approval_required' + 'x'.repeat(300),
      task_id: 't'.repeat(150),
      approval_required: true,
      screenshot: 'pixels',
      image_base64: 'base64-secret',
      path: 'C:\\private',
      tool: { driver: 'raw' },
      ran: [
        {
          action: 'read',
          status: ' RAN ',
          reason: 'r'.repeat(300),
          args: { query: 'private', text: 'typed-secret' },
          screenshot: 'pixels',
          result: {
            source: 'accessibility' + 's'.repeat(80),
            text: 'visible'.repeat(300),
            count: 4,
            truncated: true,
            elements: hostileElements,
            element: { role: 'button', name: 'Continue', value: 'secret' },
            image_base64: 'base64-secret',
            path: 'C:\\private',
            raw: { driver: true },
          },
          unknown: 'drop-me',
        },
        {
          action: 'type',
          status: 'ran',
          args: { name: 'password', text: 'typed-secret' },
          result: { text: 'typed-secret', source: 'driver', count: -1 },
        },
        { action: 'click' + 'a'.repeat(80), status: 'failed' },
        ...Array.from({ length: 20 }, () => ({ action: 'click', status: 'failed' })),
      ],
      unknown: 'drop-me',
    };

    const safe = sanitizeDesktopResult(hostile);
    expect(safe.ok).toBe(false);
    expect(safe.reason).toHaveLength(240);
    expect(safe.task_id).toHaveLength(128);
    expect(safe.approval_required).toBe(true);
    expect(safe.ran).toHaveLength(20);
    expect(safe.ran?.[2].action).toHaveLength(64);
    expect(safe.ran?.[0].status).toBe('ran');
    expect(safe.ran?.[0].reason).toHaveLength(240);
    expect(safe.ran?.[0].result?.source).toHaveLength(64);
    expect(safe.ran?.[0].result?.text).toHaveLength(1000);
    expect(safe.ran?.[0].result?.count).toBe(4);
    expect(safe.ran?.[0].result?.truncated).toBe(true);
    expect(safe.ran?.[0].result?.elements).toHaveLength(10);
    expect(safe.ran?.[0].result?.elements?.[0].role).toHaveLength(120);
    expect(safe.ran?.[0].result?.elements?.[0].name).toHaveLength(120);
    expect(safe.ran?.[0].result?.element).toEqual({ role: 'button', name: 'Continue' });
    expect(safe.ran?.[1].result).toEqual({ source: 'driver' });

    const serialized = JSON.stringify(safe);
    for (const forbidden of [
      'typed-secret', 'base64-secret', 'C:\\\\private', 'private-id',
      'automation_id', '"args"', '"unknown"', '"screenshot"', '"path"', '"raw"',
    ]) {
      expect(serialized).not.toContain(forbidden);
    }
  });

  it('normalizes the real queued reason alias and rejects unsafe task ids', () => {
    expect(sanitizeDesktopResult({ reason: 'approval_required', task_id: 7 }))
      .toEqual({ reason: 'approval_required', task_id: '7', approval_required: true, ran: [] });
    expect(sanitizeDesktopResult({ approval_required: true, task_id: { raw: true } }))
      .toEqual({ approval_required: true, ran: [] });
    expect(sanitizeDesktopResult({ reason: 'approval_required', approval_required: false, task_id: 'task-8' }))
      .toEqual({ reason: 'approval_required', task_id: 'task-8', approval_required: true, ran: [] });
  });

  it('ignores malformed roots and non-literal scalar values', () => {
    expect(sanitizeDesktopResult(null)).toEqual({ ran: [] });
    expect(sanitizeDesktopResult({ ok: 'true', reason: { toString: () => 'secret' }, ran: 'raw' }))
      .toEqual({ ran: [] });
  });
});
