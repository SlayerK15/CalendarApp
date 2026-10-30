export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message); this.status = status; this.code = code;
  }
}
const pendingReads = new Map<string, Promise<unknown>>();
const retryDelays = [5000, 15000, 30000];

function retryAfterMs(header: string | null): number | undefined {
  if (!header?.trim()) return undefined;
  const seconds = Number(header);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const date = Date.parse(header);
  return Number.isFinite(date) ? Math.max(0, date - Date.now()) : undefined;
}

// Browser requests stay first-party; the server proxy uses NEXT_PUBLIC_API_URL.
export function api<T>(path: string, body?: unknown): Promise<T> {
  // Strict Mode, polling and tab visibility can request the same data at once.
  // Share only pending GETs; never cache user data or combine mutations.
  if (body !== undefined) return request<T>(path, body);
  const pending = pendingReads.get(path);
  if (pending) return pending as Promise<T>;
  const result = request<T>(path).finally(() => pendingReads.delete(path));
  pendingReads.set(path, result);
  return result;
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { credentials: 'same-origin', cache: 'no-store',
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) };
  const deadline = Date.now() + 75000;
  let response = await fetch(`/api/${path}`, init);
  // A 429 explicitly rejects the request, so it is safe to retry even a POST.
  // Do not replay mutations after ambiguous network errors or server failures.
  for (let attempt = 0; response.status === 429 && attempt < retryDelays.length; attempt++) {
    const delay = Math.max(1000, retryAfterMs(response.headers.get('retry-after')) ?? retryDelays[attempt])
      + Math.floor(Math.random() * 1000);
    if (Date.now() + delay > deadline) break;
    await response.body?.cancel();
    await new Promise(resolve => setTimeout(resolve, delay));
    response = await fetch(`/api/${path}`, init);
  }
  const text = await response.text();
  let value;
  try { value = text ? JSON.parse(text) : undefined; }
  catch {
    if (response.ok) throw new ApiError('The API returned an invalid response. Please try again shortly.', response.status);
  }
  if (!response.ok) {
    // Hosting proxies can return plain text or HTML instead of API JSON.
    const detail = value?.detail;
    const wait = retryAfterMs(response.headers.get('retry-after'));
    const fallback = response.status === 429
      ? `The service is temporarily busy.${wait ? ` Please try again in ${Math.ceil(wait / 1000)} seconds.` : ' Please try again in a minute.'}`
      : `Request failed (${response.status}). Please try again shortly.`;
    throw new ApiError(typeof detail === 'string' ? detail : detail?.message || fallback, response.status, detail?.code);
  }
  return value as T;
}
export type TimetableEvent = {id: string; summary: string; location: string; description: string; cancelled: boolean; start: {dateTime: string}; end: {dateTime: string}};
export type SharedSync = {id: string; status: 'queued' | 'running' | 'completed' | 'failed'; total: number; processed: number; up_to_date: number; reconnect_required: number; failed: number; needs_review: number; skipped: number; message: string; requested_at: string};
export type AccountNotice = {id: string; action: 'reconnect' | 'setup'; title: string; message: string; expires_at: string};
export type NoticeCampaign = {id: string; remaining: number; total: number; expires_at: string};
export type Dashboard = {account_notice?: AccountNotice | null; notice_campaign?: NoticeCampaign | null; shared_sync?: SharedSync | null; timetable_timezone?: string; timetables: {label: string; url: string; enabled: boolean}[]; programme: string; section: string; active: boolean; pending: boolean; sync_interval_seconds: number; sync_on_change: boolean; sync_in_progress: boolean; calendar_id: string | null; last_synced_at: string | null; last_error: string | null; sync_warning?: string | null; google_reconnect_required: boolean; event_count: number; watch_active: boolean; events: TimetableEvent[]; runs: {status: string; message: string; at: string}[]};
