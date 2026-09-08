export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
// Browser requests stay first-party; the server proxy uses NEXT_PUBLIC_API_URL.
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, { credentials: 'same-origin', cache: 'no-store',
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const value = await response.json();
  if (!response.ok) throw new ApiError(typeof value.detail === 'string' ? value.detail : 'Request failed. Please try again.', response.status);
  return value;
}
export type TimetableEvent = {id: string; summary: string; location: string; description: string; cancelled: boolean; start: {dateTime: string}; end: {dateTime: string}};
export type Dashboard = {programme: string; section: string; active: boolean; pending: boolean; calendar_id: string | null; last_synced_at: string | null; last_error: string | null; event_count: number; watch_active: boolean; events: TimetableEvent[]; runs: {status: string; message: string; at: string}[]};
