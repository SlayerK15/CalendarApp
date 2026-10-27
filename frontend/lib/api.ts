export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message); this.status = status; this.code = code;
  }
}
// Browser requests stay first-party; the server proxy uses NEXT_PUBLIC_API_URL.
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, { credentials: 'same-origin', cache: 'no-store',
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  let value;
  try { value = text ? JSON.parse(text) : undefined; }
  catch {
    if (response.ok) throw new ApiError('The API returned an invalid response. Please try again shortly.', response.status);
  }
  if (!response.ok) {
    // Hosting proxies can return plain text or HTML instead of API JSON.
    const detail = value?.detail;
    const fallback = response.status === 429
      ? 'Too many requests. Please wait a moment before trying again.'
      : `Request failed (${response.status}). Please try again shortly.`;
    throw new ApiError(typeof detail === 'string' ? detail : detail?.message || fallback, response.status, detail?.code);
  }
  return value as T;
}
export type TimetableEvent = {id: string; summary: string; location: string; description: string; cancelled: boolean; start: {dateTime: string}; end: {dateTime: string}};
export type Dashboard = {timetable_timezone?: string; timetables: {label: string; url: string; enabled: boolean}[]; programme: string; section: string; active: boolean; pending: boolean; sync_interval_seconds: number; sync_on_change: boolean; sync_in_progress: boolean; calendar_id: string | null; last_synced_at: string | null; last_error: string | null; sync_warning?: string | null; google_reconnect_required: boolean; event_count: number; watch_active: boolean; events: TimetableEvent[]; runs: {status: string; message: string; at: string}[]};
