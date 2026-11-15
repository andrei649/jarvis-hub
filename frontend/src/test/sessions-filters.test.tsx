// @ts-nocheck
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { SessionsPanel } from '../panels/sessions';
import { apiGet } from '../api/client';
vi.mock('../api/client', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(), apiDownload: vi.fn() }));
const initial = [
 { id: 'a', title: 'Launch Alpha', agent_id: 'nerva', started_at: '2026-11-12T12:00:00Z', pinned_at: 'yes' },
 { id: 'b', title: 'Launch Beta', agent_id: 'ultron', started_at: '2026-11-01T12:00:00Z' },
 { id: 'c', title: 'Launch Gamma', agent_id: 'nerva', started_at: '2026-11-12T13:00:00Z' },
 { id: 'd', title: 'Undated', agent_id: null },
 { id: 'e', title: 'Malformed', agent_id: '', started_at: '2026-02-30T12:00:00Z' },
 { id: 'f', title: 'Future', agent_id: 'all', started_at: '2026-11-14T12:00:00Z' },
 { id: 'g', title: 'Old', agent_id: 'unassigned', started_at: '2026-09-01T12:00:00Z' },
 { id: 'h', title: 'Bad timestamp', agent_id: 12, started_at: 123 },
];
let rows, next, transcriptRead;
const agent = () => screen.getByLabelText('Filter loaded sessions by agent');
const date = () => screen.getByLabelText('Filter loaded sessions by date');
const search = () => screen.getByLabelText('Search loaded recent sessions');
const select = (control, value) => fireEvent.change(control, { target: { value } });
const reset = () => fireEvent.click(screen.getByRole('button', { name: 'Reset session filters' }));
const ids = () => screen.queryAllByRole('button', { name: /^resume / }).map(el => el.getAttribute('aria-label').slice(7));
beforeEach(() => {
 vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-11-13T12:00:00Z'));
 rows = initial; next = null; transcriptRead = undefined;
 vi.mocked(apiGet).mockImplementation(async path => {
  if (path.endsWith('/transcript')) return transcriptRead;
  const url = new URL(path, 'http://test');
  return { sessions: url.searchParams.has('cursor') ? [{ id: 'later', title: 'Launch Later', agent_id: 'frigga', started_at: '2026-11-12T14:00:00Z' }] : rows, next_cursor: url.searchParams.has('cursor') ? null : next };
 });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });
async function setup() { render(<SessionsPanel />); await screen.findByText('Launch Alpha'); }
describe('loaded session filters and date groups', () => {
 it('combines exact agent, date and literal metadata search without fetching', async () => {
  await setup(); const reads = vi.mocked(apiGet).mock.calls.length;
  select(agent(), 'agent:nerva'); select(date(), '7'); select(search(), '  launch  '); expect(ids()).toEqual(['a', 'c']);
  select(date(), '30'); select(agent(), 'agent:ultron'); expect(ids()).toEqual(['b']);
  select(search(), 'absent'); expect(screen.getByText('No loaded sessions match these filters')).toBeTruthy();
  select(search(), ''); reset(); expect(ids()).toEqual(initial.map(row => row.id));
  expect(vi.mocked(apiGet).mock.calls.length).toBe(reads); expect(screen.getByText(/Filters apply to all pages loaded here/)).toBeTruthy();
 });
 it('keeps invalid dates unknown, bounds recent ranges and distinguishes sentinel agent names', async () => {
  await setup(); select(date(), 'unknown'); expect(ids()).toEqual(['d', 'e', 'h']);
  select(agent(), 'unassigned'); expect(ids()).toEqual(['d', 'e', 'h']);
  reset(); select(date(), '7'); expect(ids()).toEqual(['a', 'c']);
  select(date(), '30'); expect(ids()).toEqual(['a', 'b', 'c']);
  reset(); select(agent(), 'agent:all'); expect(ids()).toEqual(['f']);
  select(agent(), 'agent:unassigned'); expect(ids()).toEqual(['g']);
 });
 it('includes exact rolling boundaries and rejects malformed ISO timestamps without browser normalization', async () => {
  rows = [initial[0],
   { id: 'now', started_at: '2026-11-13T12:00:00Z' },
   { id: 'seven', started_at: '2026-11-06T12:00:00Z' },
   { id: 'before-seven', started_at: '2026-11-06T11:59:59Z' },
   { id: 'thirty', started_at: '2026-10-14T12:00:00Z' },
   { id: 'before-thirty', started_at: '2026-10-14T11:59:59Z' },
   { id: 'after-now', started_at: '2026-11-13T12:00:00.001Z' },
   { id: 'invalid-hour', started_at: '2026-11-12T24:00:00Z' },
   { id: 'invalid-month', started_at: '2026-13-01T12:00:00Z' },
   { id: 'natural-date', started_at: 'November 12, 2026' },
   { id: 'offset', started_at: '2026-11-06T14:00:00+02:00' },
   { id: 'fraction', started_at: '2026-11-12T12:00:00.123456+00:00' },
  ];
  await setup(); select(date(), '7'); expect(ids()).toEqual(['a', 'now', 'seven', 'offset', 'fraction']);
  select(date(), '30'); expect(ids()).toEqual(['a', 'now', 'seven', 'before-seven', 'thirty', 'offset', 'fraction']);
  select(date(), 'unknown'); expect(ids()).toEqual(['invalid-hour', 'invalid-month', 'natural-date']);
 });
 it('retains an exact selected agent with a truthful empty result after refresh removes its rows', async () => {
  await setup(); select(agent(), 'agent:ultron'); select(search(), 'Launch');
  rows = [initial[0]]; fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
  await screen.findByText('No loaded sessions match these filters');
  expect(agent().value).toBe('agent:ultron'); expect(search().value).toBe('Launch');
  reset(); expect(search().value).toBe('Launch'); expect(ids()).toEqual(['a']);
 });
 it('groups contiguous local calendar dates in API order without sorting pinned rows', async () => {
  await setup(); const label = value => new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(value));
  expect(screen.getAllByTestId('session-date-group').map(el => el.textContent)).toEqual([label(initial[0].started_at), label(initial[1].started_at), label(initial[2].started_at), 'Unknown date', label(initial[5].started_at), label(initial[6].started_at), 'Unknown date']);
  expect(ids()).toEqual(initial.map(row => row.id)); expect(screen.getByTestId('pinned-badge')).toBeTruthy();
 });
 it('extends agent choices and matching search across appended pages', async () => {
  next = 'older'; await setup(); select(search(), 'Launch Later'); expect(within(agent()).queryByRole('option', { name: 'frigga' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Load older sessions' })); await screen.findByText('Launch Later');
  expect(within(agent()).getByRole('option', { name: 'frigga' })).toBeTruthy(); select(agent(), 'agent:frigga'); select(date(), '7'); expect(ids()).toEqual(['later']);
 });
 it('retains filters on refresh and resets filters and query on tab changes, clearing pending actions', async () => {
  await setup(); select(agent(), 'agent:nerva'); select(date(), '7'); select(search(), 'Launch');
  fireEvent.click(screen.getByRole('button', { name: 'Reload' })); await screen.findByText('Launch Alpha');
  expect(agent().value).toBe('agent:nerva'); expect(date().value).toBe('7'); expect(search().value).toBe('Launch');
  fireEvent.click(screen.getByRole('tab', { name: 'archived' })); await screen.findByText('Launch Beta');
  expect(agent().value).toBe('all'); expect(date().value).toBe('all'); expect(search().value).toBe('');
  fireEvent.click(screen.getByLabelText('delete a permanently')); expect(screen.getByLabelText('confirm delete a')).toBeTruthy();
  select(date(), '7'); expect(screen.queryByLabelText('confirm delete a')).toBeNull();
  fireEvent.click(screen.getByLabelText('rename a')); expect(screen.getByLabelText('title for a')).toBeTruthy();
  select(agent(), 'agent:nerva'); expect(screen.queryByLabelText('title for a')).toBeNull();
 });
 it.each(['agent', 'date', 'reset'])('fences private transcript replies after a %s change while row remains', async control => {
  await setup(); if (control === 'reset') select(date(), '7');
  let resolve; transcriptRead = new Promise(done => { resolve = done; }); fireEvent.click(screen.getByLabelText('preview retained conversation a'));
  if (control === 'agent') select(agent(), 'agent:nerva'); if (control === 'date') select(date(), '7'); if (control === 'reset') reset();
  await act(async () => { resolve({ schema_version: 1, session_id: 'a', scope: 'retained_current_history', redacted: true, turn_count: 1, turns: [{ role: 'user', content: 'private reply', agent_id: null, timestamp: '' }] }); });
  expect(screen.queryByText('private reply')).toBeNull(); expect(screen.queryByLabelText('retained conversation a')).toBeNull(); expect(screen.getByLabelText('resume a')).toBeTruthy();
 });
});
