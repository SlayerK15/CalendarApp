import { NextRequest } from 'next/server';
export const dynamic = 'force-dynamic';
const allowed = new Set(['me', 'options', 'dashboard', 'subscription', 'sync', 'auth/google/start', 'auth/exchange', 'auth/logout']);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const endpoint = path.join('/');
  if (!allowed.has(endpoint)) return Response.json({ detail: 'Not found' }, { status: 404 });
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (!base) return Response.json({ detail: 'Set NEXT_PUBLIC_API_URL on the frontend deployment.' }, { status: 503 });
  const headers = new Headers();
  for (const name of ['content-type', 'cookie', 'origin']) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(`${base.replace(/\/$/, '')}/api/${endpoint}`, {
      method: request.method, headers, redirect: 'manual', cache: 'no-store',
      body: request.method === 'POST' ? await request.text() : undefined,
      signal: AbortSignal.timeout(55000),
    });
    const outgoing = new Headers({ 'Content-Type': upstream.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store' });
    for (const cookie of upstream.headers.getSetCookie()) outgoing.append('Set-Cookie', cookie);
    return new Response(upstream.body, { status: upstream.status, headers: outgoing });
  } catch {
    return Response.json({ detail: 'The API is unavailable. Please try again shortly.' }, { status: 502 });
  }
}
export const GET = proxy;
export const POST = proxy;
