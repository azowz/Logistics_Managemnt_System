import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { request, setAuthToken, onUnauthorized, ApiError, USE_MOCK } from '../src/api/client';
import { driverApi } from '../src/api/driverApi';

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; setAuthToken(null); onUnauthorized(null); });

test('live is the default; requests preserve JWT and request id, handle 204', async () => {
  assert.equal(USE_MOCK, false);
  setAuthToken('existing-jwt');
  globalThis.fetch = async (url, options) => {
    assert.match(String(url), /\/v1\/shipments\/id\/decline$/);
    assert.equal(new Headers(options?.headers).get('Authorization'), 'Bearer existing-jwt');
    assert.ok(new Headers(options?.headers).get('X-Request-ID'));
    return new Response(null, { status: 204 });
  };
  assert.equal(await driverApi.declineOrder('id'), undefined);
});

test('connection errors are actionable and never return fixtures', async () => {
  globalThis.fetch = async () => { throw new TypeError('offline'); };
  await assert.rejects(driverApi.getNearbyRequests(), (error: unknown) => error instanceof ApiError && error.status === 0);
});

test('domain error code/details and server request id survive the client', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ error: {
    code: 'concurrency_conflict', message: 'Reload shipment', details: { version: 2 }, request_id: 'body-id',
  } }), { status: 409, headers: { 'X-Request-ID': 'server-id' } });
  await assert.rejects(request('/shipments/id'), (error: unknown) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, 'concurrency_conflict');
    assert.equal(error.requestId, 'server-id');
    assert.deepEqual(error.details, { version: 2 });
    return true;
  });
});

test('401 expires an authenticated session, while 403 preserves it', async () => {
  let expired = 0;
  onUnauthorized(() => { expired++; });
  setAuthToken('jwt');
  for (const status of [403, 401]) {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Denied' }), { status });
    await assert.rejects(request('/drivers/me'), (error: unknown) => error instanceof ApiError && error.status === status);
  }
  assert.equal(expired, 1);
});

test('validation envelopes and non-JSON failures are handled', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'phone'], msg: 'required' }] }), { status: 422 });
  await assert.rejects(request('/auth/driver/login'), (error: unknown) => error instanceof ApiError && Array.isArray(error.details));
  globalThis.fetch = async () => new Response('Bad gateway', { status: 502 });
  await assert.rejects(request('/drivers/me'), (error: unknown) => error instanceof ApiError && error.status === 502);
});

test('phone login uses the existing driver endpoint and maps its response', async () => {
  const urls: string[] = [];
  globalThis.fetch = async (url, options) => {
    urls.push(String(url));
    if (String(url).endsWith('/auth/me')) return Response.json({ full_name: 'سائق الاختبار' });
    assert.deepEqual(JSON.parse(String(options?.body)), { phone: '+966512345678' });
    return Response.json({ access_token: 'jwt', driver: {
      id: 'driver', user_id: 'user', phone_number: '+966512345678', is_available: true,
    } });
  };
  const login = await driverApi.login('0512345678');
  assert.ok(urls[0].endsWith('/v1/auth/driver/login'));
  assert.equal(login.driver.fullName, 'سائق الاختبار');
  assert.equal(login.driver.vehicleType, null);
});

test('password login preserves tenant_slug and rejects non-driver access', async () => {
  globalThis.fetch = async (url, options) => {
    if (String(url).endsWith('/auth/login')) {
      assert.deepEqual(JSON.parse(String(options?.body)), { email: 'driver@example.com', password: 'password', tenant_slug: 'tenant-a' });
      return Response.json({ access_token: 'jwt', refresh_token: 'refresh', user: { full_name: 'Driver' } });
    }
    return new Response(JSON.stringify({ detail: 'Drivers only' }), { status: 403 });
  };
  await assert.rejects(driverApi.loginWithPassword('driver@example.com', 'password', 'tenant-a'),
    (error: unknown) => error instanceof ApiError && error.status === 403);
});

test('snake_case offers/stats map correctly and missing data stays absent', async () => {
  globalThis.fetch = async (url) => String(url).endsWith('/stats')
    ? Response.json({ earnings_sar: 420, trips: 1, online_hours: 2, distance_km: 10, date: '2026-11-11' })
    : Response.json([{ id: 'offer', reference_code: 'SHP-1', weight_kg: 3200, origin_city: 'الرياض' }]);
  assert.deepEqual(await driverApi.getDailyStats(), { earningsSar: 420, trips: 1, onlineHours: 2, distanceKm: 10, date: '2026-11-11' });
  const [offer] = await driverApi.getNearbyRequests();
  assert.equal(offer.originCity, 'الرياض');
  assert.equal(offer.priceSar, null);
  assert.equal(offer.origin, null);
  assert.equal(offer.postedMinutesAgo, null);
});

test('availability maps DriverRead and shipment detail preserves server state', async () => {
  globalThis.fetch = async (url, options) => String(url).endsWith('/drivers/me')
    ? Response.json({ is_available: false })
    : Response.json({ id: 'id', reference_code: 'SHP-1', status: 'picked_up', price_sar: '420.50', weight_kg: '3200' });
  assert.deepEqual(await driverApi.setAvailability(false), { isAvailable: false });
  const order = await driverApi.getOrder('id');
  assert.equal(order.status, 'picked_up');
  assert.equal(order.priceSar, 420.5);
  assert.equal(order.company, null);
  assert.equal(order.offerWindowSeconds, null);
});

test('caller cancellation cannot leave a request pending', async () => {
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async (_, options) => {
    assert.equal(options?.signal?.aborted, true);
    throw new DOMException('Aborted', 'AbortError');
  };
  await assert.rejects(request('/drivers/me', { signal: controller.signal }), ApiError);
});
