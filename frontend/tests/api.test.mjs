import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { api, ApiError } from '../lib/api.ts';
import { GET, POST } from '../app/api/[...path]/route.ts';

const originalFetch = globalThis.fetch;
const originalBase = process.env.NEXT_PUBLIC_API_URL;
afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalBase === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = originalBase;
});

test('plain-text rate limits retain HTTP status and show a useful message', async () => {
  globalThis.fetch = async () => new Response('Too many requests', { status: 429 });
  await assert.rejects(api('dashboard'), error => error instanceof ApiError && error.status === 429 && /Too many requests/.test(error.message));
});

test('HTML gateway errors do not surface JSON parsing errors or raw markup', async () => {
  globalThis.fetch = async () => new Response('<html>Bad gateway</html>', { status: 502 });
  await assert.rejects(api('dashboard'), error => error instanceof ApiError && error.status === 502 && !/html|Unexpected token/.test(error.message));
});

test('structured reconnect errors retain their message, code and status', async () => {
  globalThis.fetch = async () => Response.json({ detail: { message: 'Reconnect Google', code: 'google_reconnect_required' } }, { status: 403 });
  await assert.rejects(api('options'), error => error.message === 'Reconnect Google' && error.code === 'google_reconnect_required' && error.status === 403);
});

test('successful JSON and empty responses are accepted', async () => {
  globalThis.fetch = async () => Response.json({ name: 'Test' });
  assert.deepEqual(await api('me'), { name: 'Test' });
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await api('auth/logout', {}), undefined);
});

test('a non-JSON success produces a controlled error', async () => {
  globalThis.fetch = async () => new Response('<html>Wrong server</html>');
  await assert.rejects(api('me'), error => error instanceof ApiError && /invalid response/.test(error.message));
});

test('self-referencing API URL fails before fetching recursively', async () => {
  process.env.NEXT_PUBLIC_API_URL = 'https://frontend.example';
  globalThis.fetch = async () => { assert.fail('must not make an upstream request'); };
  const response = await GET(new Request('https://frontend.example/api/me'), { params: Promise.resolve({ path: ['me'] }) });
  assert.equal(response.status, 503);
  assert.match((await response.json()).detail, /FastAPI backend URL/);
});

test('self-reference is detected behind a reverse proxy', async () => {
  process.env.NEXT_PUBLIC_API_URL = 'https://frontend.example';
  globalThis.fetch = async () => { assert.fail('must not make an upstream request'); };
  const response = await GET(new Request('http://localhost:10000/api/me', { headers: { 'x-forwarded-host': 'frontend.example' } }), { params: Promise.resolve({ path: ['me'] }) });
  assert.equal(response.status, 503);
});

test('proxy preserves upstream rate-limit status and Retry-After', async () => {
  process.env.NEXT_PUBLIC_API_URL = 'https://backend.example';
  globalThis.fetch = async url => {
    assert.equal(url.href, 'https://backend.example/api/me');
    return new Response('Too many requests', { status: 429, headers: { 'Retry-After': '60', 'Content-Type': 'text/plain' } });
  };
  const response = await GET(new Request('https://frontend.example/api/me'), { params: Promise.resolve({ path: ['me'] }) });
  assert.equal(response.status, 429);
  assert.equal(response.headers.get('retry-after'), '60');
  assert.equal(await response.text(), 'Too many requests');
});


test('master timetable connection reaches the authenticated backend route', async () => {
  process.env.NEXT_PUBLIC_API_URL = 'https://backend.example';
  globalThis.fetch = async (url, init) => {
    assert.equal(url.href, 'https://backend.example/api/admin/timetable/connect');
    assert.equal(init.method, 'POST');
    assert.equal(init.headers.get('cookie'), 'lt_session=test');
    return Response.json({ url: 'https://accounts.google.com/example' });
  };
  const response = await POST(new Request('https://frontend.example/api/admin/timetable/connect', {
    method: 'POST', headers: { cookie: 'lt_session=test', origin: 'https://frontend.example' }, body: '{}',
  }), { params: Promise.resolve({ path: ['admin', 'timetable', 'connect'] }) });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { url: 'https://accounts.google.com/example' });
});
