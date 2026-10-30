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

function fastRetries(t) {
  let now = Date.now();
  const delays = [];
  t.mock.method(Date, 'now', () => now);
  t.mock.method(Math, 'random', () => 0);
  t.mock.method(globalThis, 'setTimeout', (resolve, delay) => {
    delays.push(delay);
    now += delay;
    queueMicrotask(resolve);
    return 0;
  });
  return delays;
}

test('persistent plain-text rate limits stop after three retries with a useful error', async t => {
  const delays = fastRetries(t);
  globalThis.fetch = async () => new Response('Too many requests', { status: 429 });
  await assert.rejects(api('dashboard'), error => error instanceof ApiError && error.status === 429 && /temporarily busy/.test(error.message));
  assert.deepEqual(delays, [5000, 15000, 30000]);
});

test('a transient rate limit recovers automatically', async t => {
  const delays = fastRetries(t);
  let calls = 0;
  globalThis.fetch = async () => ++calls === 1
    ? new Response('Too Many Requests', { status: 429 })
    : Response.json({ name: 'Test' });
  assert.deepEqual(await api('me'), { name: 'Test' });
  assert.equal(calls, 2);
  assert.deepEqual(delays, [5000]);
});

test('Retry-After seconds and HTTP dates are respected', async t => {
  const delays = fastRetries(t);
  const headers = ['10', new Date(Date.now() + 30000).toUTCString()];
  let calls = 0;
  globalThis.fetch = async () => calls < headers.length
    ? new Response(null, { status: 429, headers: { 'Retry-After': headers[calls++] } })
    : Response.json({ ok: true });
  assert.deepEqual(await api('me'), { ok: true });
  assert.equal(delays[0], 10000);
  assert.ok(delays[1] >= 19000 && delays[1] <= 20000);
});

test('a server cooldown beyond the retry budget is reported without retrying early', async t => {
  const delays = fastRetries(t);
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response(null, { status: 429, headers: { 'Retry-After': '120' } });
  };
  await assert.rejects(api('dashboard'), error => error.status === 429 && /120 seconds/.test(error.message));
  assert.equal(calls, 1);
  assert.deepEqual(delays, []);
});

test('invalid Retry-After uses backoff and zero still waits before retrying', async t => {
  const delays = fastRetries(t);
  const headers = ['invalid', '0'];
  let calls = 0;
  globalThis.fetch = async () => calls < headers.length
    ? new Response(null, { status: 429, headers: { 'Retry-After': headers[calls++] } })
    : Response.json({ ok: true });
  await api('me');
  assert.deepEqual(delays, [5000, 1000]);
});

test('only explicitly rate-limited POSTs are replayed, preserving the body', async t => {
  fastRetries(t);
  const bodies = [];
  globalThis.fetch = async (_url, init) => {
    assert.equal(init.method, 'POST');
    bodies.push(init.body);
    return bodies.length === 1 ? new Response(null, { status: 429 }) : Response.json({ ok: true });
  };
  await api('auth/exchange', { ticket: 'test' });
  assert.deepEqual(bodies, ['{"ticket":"test"}', '{"ticket":"test"}']);
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(null, { status: 502 }); };
  await assert.rejects(api('sync', {}), error => error.status === 502);
  assert.equal(calls, 1);
  globalThis.fetch = async () => { calls++; throw new TypeError('Network error'); };
  await assert.rejects(api('sync', {}), /Network error/);
  assert.equal(calls, 2);
});

test('overlapping GETs share a request but subsequent reads fetch fresh data', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({ version: calls }); };
  const results = await Promise.all([api('dashboard'), api('dashboard')]);
  assert.deepEqual(results, [{ version: 1 }, { version: 1 }]);
  assert.equal(calls, 1);
  assert.deepEqual(await api('dashboard'), { version: 2 });
});

test('a failed shared read can be requested again', async () => {
  globalThis.fetch = async () => { throw new TypeError('Offline'); };
  const results = await Promise.allSettled([api('dashboard'), api('dashboard')]);
  assert.ok(results.every(result => result.status === 'rejected'));
  globalThis.fetch = async () => Response.json({ recovered: true });
  assert.deepEqual(await api('dashboard'), { recovered: true });
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
