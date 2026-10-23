import type { Task } from './api/types';

export function effectiveTaskState(task: Task): string {
  const state = typeof task?.state === 'string' && task.state.trim()
    ? task.state
    : task?.status;
  return typeof state === 'string' ? state.trim().toLowerCase() : '';
}

export function runningTasks(tasks: Task[] | null | undefined): Task[] {
  if (!Array.isArray(tasks) || tasks.length === 0) return [];
  // Bolt Optimization: Single indexed loop avoids callback closure allocations from .filter()
  // during canvas frame rendering (burst.tsx, mesh.tsx) and high-frequency UI updates.
  const out: Task[] = [];
  for (let i = 0; i < tasks.length; i++) {
    const task = tasks[i];
    if (effectiveTaskState(task) === 'running') {
      out.push(task);
    }
  }
  return out;
}
