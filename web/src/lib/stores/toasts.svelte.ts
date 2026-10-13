export interface Toast {
  id: number;
  message: string;
  error: boolean;
  action?: { label: string; run: () => void };
}

export const toasts: Toast[] = $state([]);
let nextId = 1;

export function toast(message: string, opts: { error?: boolean; duration?: number; action?: Toast["action"] } = {}) {
  const id = nextId++;
  toasts.push({ id, message, error: !!opts.error, action: opts.action });
  const duration = opts.duration ?? (opts.error ? 7000 : 3500);
  setTimeout(() => dismiss(id), duration);
  return id;
}

export function dismiss(id: number) {
  const i = toasts.findIndex((t) => t.id === id);
  if (i >= 0) toasts.splice(i, 1);
}

export function reportError(err: unknown, fallback = "That did not work.") {
  const message = err instanceof Error ? err.message : fallback;
  toast(message || fallback, { error: true });
}
