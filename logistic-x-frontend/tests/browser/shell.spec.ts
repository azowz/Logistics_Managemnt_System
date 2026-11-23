import { test, expect } from '@playwright/test';

test('Arabic RTL shell, responsive login, and protected navigation work without an API', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/v1/**', (route) => route.abort());
  await page.goto('/driver/home');
  await expect(page.getByLabel('البريد الإلكتروني')).toBeVisible();
  await expect(page).toHaveURL(/\/auth\/login/);
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByText('وضع تجريبي', { exact: false })).toHaveCount(0);
  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await page.screenshot({ path: 'test-results/login-desktop.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('offline login shows a connection error and remains usable', async ({ page }) => {
  await page.route('**/v1/**', (route) => route.abort());
  await page.goto('/auth/login');
  await page.getByLabel('البريد الإلكتروني').fill('driver@example.com');
  await page.getByLabel('كلمة المرور', { exact: true }).fill('test-password');
  await page.getByText('تسجيل الدخول', { exact: true }).click();
  await expect(page.getByText('تعذّر الاتصال بالخادم.', { exact: false })).toBeVisible();
  await expect(page.getByLabel('البريد الإلكتروني')).toBeEnabled();
});
