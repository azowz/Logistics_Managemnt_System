// Optional workspace verification only. Controls the disposable test project.
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { chromium } from '../mesaar-frontend/node_modules/playwright/index.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const compose = ['compose', '-p', 'mesaar-separation-verify', '-f', resolve(root, 'docker-compose.yml'), '-f', resolve(root, 'compose.verify.yml')];
const docker = (...args) => execFileSync('docker', [...compose, ...args], { encoding: 'utf8' }).trim();
const backend = 'http://127.0.0.1:18000';
const frontend = 'http://127.0.0.1:18081';
async function ready(url) {
  for (let i = 0; i < 45; i++) {
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Not ready: ${url}`);
}
await ready(`${backend}/health/ready`);
const browser = await chromium.launch();
const page = await browser.newPage();
try {
  await page.goto(`${frontend}/auth/login`);
  await page.getByLabel('البريد الإلكتروني').waitFor();
  const frontendId = docker('ps', '-q', 'frontend');
  docker('stop', 'api');
  await page.getByLabel('البريد الإلكتروني').fill('offline-test@example.com');
  await page.getByLabel('كلمة المرور', { exact: true }).fill('test-password');
  await page.getByText('تسجيل الدخول', { exact: true }).click();
  await page.getByText('تعذّر الاتصال بالخادم.', { exact: false }).waitFor();
  assert.equal(docker('ps', '-q', 'frontend'), frontendId);
  docker('start', 'api');
  await ready(`${backend}/health/ready`);
  const response = page.waitForResponse((r) => r.url().endsWith('/v1/auth/login'));
  await page.getByText('تسجيل الدخول', { exact: true }).click();
  assert.equal((await response).status(), 401);

  const apiId = docker('ps', '-q', 'api');
  const started = execFileSync('docker', ['inspect', '-f', '{{.State.StartedAt}}', apiId], { encoding: 'utf8' });
  docker('stop', 'frontend');
  assert.equal((await fetch(`${backend}/health/ready`)).status, 200);
  docker('start', 'frontend');
  await ready(`${frontend}/health`);
  assert.equal(execFileSync('docker', ['inspect', '-f', '{{.State.StartedAt}}', apiId], { encoding: 'utf8' }), started);
  await page.goto(`${frontend}/auth/login`);
  await page.getByLabel('البريد الإلكتروني').waitFor();
  const artifacts = resolve(root, '.verification');
  await mkdir(artifacts, { recursive: true });
  for (const [label, width] of [['mobile', 320], ['desktop', 1280]]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: resolve(artifacts, `login-${label}.png`), fullPage: true });
  }
  console.log('PASS: API stop/recovery with the browser shell running; frontend stop/recovery without restarting API; mobile/desktop RTL shell.');
} finally {
  docker('start', 'api', 'frontend');
  await browser.close();
}
