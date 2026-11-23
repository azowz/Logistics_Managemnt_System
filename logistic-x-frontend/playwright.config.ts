import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: process.env.FRONTEND_TEST_URL ?? 'http://127.0.0.1:8081', trace: 'retain-on-failure' },
  webServer: process.env.FRONTEND_TEST_URL ? undefined : {
    command: 'npm run preview',
    url: 'http://127.0.0.1:8081',
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: 'standalone', testMatch: /shell\.spec\.ts/, use: { ...devices['Desktop Chrome'] } },
    { name: 'integration', testMatch: /integration\.spec\.ts/, use: { ...devices['Desktop Chrome'] } },
  ],
});
