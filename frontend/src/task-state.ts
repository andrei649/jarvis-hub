import type { Task } from './api/types';

export function effectiveTaskState(task: Task): string {
  const state = typeof task?.state === 'string' && task.state.trim()
    ? task.state
    : task?.status;
  return typeof state === 'string' ? state.trim().toLowerCase() : '';
}

export function runningTasks(tasks: Task[] | null | undefined): Task[] {
  return Array.isArray(tasks)
    ? tasks.filter((task) => effectiveTaskState(task) === 'running')
    : [];
}
