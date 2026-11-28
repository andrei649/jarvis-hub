import { beforeEach, describe, expect, jest, test } from '@jest/globals';
import sharedCases from '../../../../frontend/src/test/recall-line-cases.json';
import { Conversation } from '../../chat/conversation';
import { normalizeTurnOutcome, recallLine, recallLines, turnRecall, turnRecalls } from '../../chat/turnOutcome';
import type { StreamHandlers } from '../client';
import type { ServerConfig } from '../../storage/settings';

jest.mock('../../storage/chat', () => ({
  loadConversation: jest.fn(async () => ({ sessionId: 's_recall', messages: [] })),
  saveConversation: jest.fn(async () => undefined),
}));

const mockStreamChat = jest.fn<(...args: any[]) => () => void>();
jest.mock('../client', () => {
  const actual = jest.requireActual('../client') as Record<string, unknown>;
  return {
    ...actual,
    streamChat: (...args: unknown[]) => mockStreamChat(...args),
  };
});

const cfg: ServerConfig = {
  baseUrl: 'https://hub.example',
  token: 'user-tok',
  adminToken: 'admin-tok',
};

describe('H18.36 / H430 native per-turn recall indicator', () => {
  beforeEach(() => {
    mockStreamChat.mockReset();
  });

  test('matches every shared recall-line-cases.json single status and turn fixture', () => {
    for (const c of sharedCases.statuses) {
      const parsed = turnRecall(c.status);
      const actual = parsed ? recallLine(parsed) : '';
      expect(actual).toBe(c.line);
    }

    for (const t of sharedCases.turns) {
      const parsed = turnRecalls(t.recall);
      const actual = parsed ? recallLines(parsed) : [];
      expect(actual).toEqual(t.lines);
    }
  });

  test('normalizeTurnOutcome extracts validated recall statuses and rejects malformed extra keys', () => {
    const valid = normalizeTurnOutcome({
      latency_ms: 120,
      recall: [
        {
          schema: 'nerva.recall-status.v1',
          provider: 'long_term_memory',
          basis: 'this_turn',
          recalled: 2,
          withheld: { rejected_taint: 1 },
          untrusted: 0,
        },
        {
          schema: 'nerva.recall-status.v1',
          provider: 'long_term_memory',
          basis: 'this_turn',
          recalled: 1,
          withheld: {},
          untrusted: 0,
          leaked_text: 'must never enter state',
        },
      ],
    });
    expect(valid?.recall).toHaveLength(1);
    expect(recallLines(valid?.recall ?? [])).toEqual([
      '🧠 Long-term memory — recalled 2 memories, 1 withheld (taint: 1)',
    ]);
  });

  test('Conversation attaches recall only onto completed native assistant replies and keeps reply text clean for TTS', async () => {
    mockStreamChat.mockImplementation((_c: unknown, _msg: unknown, _agent: unknown, handlers: StreamHandlers) => {
      handlers.onStart?.('jarvis');
      handlers.onToken('Plain spoken answer.');
      handlers.onDone('Plain spoken answer.', 's_recall', normalizeTurnOutcome({
        recall: [
          {
            schema: 'nerva.recall-status.v1',
            provider: 'message_archive',
            basis: 'this_turn',
            recalled: 3,
            withheld: {},
            untrusted: 0,
          },
        ],
      }) ?? undefined);
      return () => undefined;
    });

    const conv = new Conversation(cfg, 'scope', () => undefined);
    await conv.hydrate();
    expect(conv.send('What did we discuss?', 'jarvis')).toBe(true);

    const bot = conv.state.messages.find(m => m.role === 'assistant');
    expect(bot?.completed).toBe(true);
    expect(bot?.text).toBe('Plain spoken answer.');
    expect(recallLines(bot?.recall ?? [])).toEqual([
      '🧠 Message archive — recalled 3 memories',
    ]);
  });
});
