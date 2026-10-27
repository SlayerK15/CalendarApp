import type { NextRequest } from 'next/server';
export const dynamic = 'force-dynamic';
const allowed = new Set(['me', 'options', 'dashboard', 'subscription', 'sync', 'auth/google/start', 'auth/exchange', 'auth/logout', 'admin/timetable/connect']);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const endpoint = path.join('/');
  if (!allowed.has(endpoint)) return Response.json({ detail: 'Not found' }, { status: 404 });
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) return Response.json({ detail: 'Set NEXT_PUBLIC_API_URL on the frontend deployment.' }, { status: 503 });
  // A frontend URL here would recursively proxy /api/* back to this route.
  let target: URL;
  try {
    target = new URL(`${base.replace(/\/$/, '')}/api/${endpoint}`);
    if (!['http:', 'https:'].includes(target.protocol)) throw new Error('Invalid protocol');
  } catch {
    return Response.json({ detail: 'NEXT_PUBLIC_API_URL must be a valid backend URL.' }, { status: 503 });
  }
  const forwardedHost = request.headers.get('x-forwarded-host')?.split(',')[0].trim();
  if (target.host === new URL(request.url).host || (forwardedHost && target.host === forwardedHost)) {
    return Response.json({ detail: 'NEXT_PUBLIC_API_URL points to the frontend. Set it to the FastAPI backend URL.' }, { status: 503 });
  }
  const headers = new Headers();
  for (const name of ['content-type', 'cookie', 'origin']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(target, {
      method: request.method, headers, redirect: 'manual', cache: 'no-store',
      body: request.method === 'POST' ? await request.text() : undefined,
      signal: AbortSignal.timeout(55000),
    });
    const outgoing = new Headers({ 'Content-Type': upstream.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store' });
    const retryAfter = upstream.headers.get('retry-after');
    if (retryAfter) outgoing.set('Retry-After', retryAfter);
    for (const cookie of upstream.headers.getSetCookie()) outgoing.append('Set-Cookie', cookie);
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: 'The API is unavailable. Please try again shortly.' }, { status: 502 });
  }
}
export const GET = proxy;
export const POST = proxy;
