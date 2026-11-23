import { test, expect } from '@playwright/test';

// Run explicitly against a separately started backend and disposable database.
// This test creates a uniquely named tenant through public APIs; no auth overrides.
test('real JWT login, CORS, offers, decline 204, acceptance, and logout', async ({ page, request }) => {
  test.setTimeout(60000);
  const api = process.env.LOGISTIC_X_TEST_API_URL ?? 'http://localhost:8000/v1';
  const suffix = Date.now().toString(36);
  const tenant = `separation-${suffix}`;
  const password = 'separation-test-password';
  const registered = await request.post(`${api}/auth/register`, { data: {
    email: `admin-${suffix}@example.com`, password, organization_name: 'Separation test', tenant_slug: tenant,
  } });
  expect(registered.status(), await registered.text()).toBe(201);
  const session = await registered.json();
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const create = async (path: string, data: object) => {
    const response = await request.post(`${api}${path}`, { headers, data });
    expect(response.status(), await response.text()).toBe(201);
    return response.json();
  };
  const user = await create('/users', { email: `driver-${suffix}@example.com`, password, full_name: 'سائق الاختبار', role: 'driver' });
  await create('/drivers', { user_id: user.id, license_number: `LIC-${suffix}`, phone_number: '+966512345678' });
  const origin = await create('/warehouses', { code: 'ORIGIN', name: 'مستودع الرياض', address_line1: 'test', city: 'الرياض', country: 'SA', latitude: 24.7, longitude: 46.6, capacity_weight_kg: 100000, capacity_volume_m3: 100000 });
  const dest = await create('/warehouses', { code: 'DEST', name: 'مستودع جدة', address_line1: 'test', city: 'جدة', country: 'SA', latitude: 21.4, longitude: 39.1, capacity_weight_kg: 100000, capacity_volume_m3: 100000 });
  const shipment = await create('/shipments', { client_id: session.user.id, origin_warehouse_id: origin.id,
    destination_warehouse_id: dest.id, weight_kg: 100, volume_m3: 1, price_sar: 420, cargo_type: 'تمور', reference_code: `SHP-${suffix}` });
  const ready = await request.post(`${api}/shipments/${shipment.id}/ready`, { headers });
  expect(ready.status(), await ready.text()).toBe(200);

  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/auth/login');
  await page.getByLabel('البريد الإلكتروني').fill(user.email);
  await page.getByLabel('كلمة المرور', { exact: true }).fill(password);
  await page.getByLabel('معرّف المؤسسة', { exact: true }).fill(tenant);
  await page.getByText('تسجيل الدخول', { exact: true }).click();
  await expect(page).toHaveURL(/\/driver\/home/);
  await expect(page.getByText('سائق', { exact: false }).first()).toBeVisible();
  await expect(page.getByText('تمور', { exact: false })).toBeVisible();
  await page.getByText('تمور', { exact: false }).click();
  await expect(page).toHaveURL(new RegExp(shipment.id));
  await expect(page.getByText('إحداثيات المسار غير متاحة')).toBeVisible();
  // Live offers have no deadline: the screen must not dismiss after the old 15s timer.
  await page.waitForTimeout(16000);
  await expect(page).toHaveURL(new RegExp(shipment.id));
  const declined = page.waitForResponse((r) => r.url().endsWith('/decline'));
  await page.getByText('تجاهل', { exact: true }).click();
  expect((await declined).status()).toBe(204);
  await expect(page).toHaveURL(/\/driver\/home/);
  await page.getByText('تمور', { exact: false }).click();
  await page.getByText('قبول الطلب', { exact: true }).click();
  await expect(page.getByText('تم قبول الطلب', { exact: true })).toBeVisible();
  const actual = await request.get(`${api}/shipments/${shipment.id}`, { headers });
  expect((await actual.json()).status).toBe('assigned');
  await page.goto('/driver/home');
  await page.getByText('تسجيل الخروج', { exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/login/);
  expect(errors).toEqual([]);
});
