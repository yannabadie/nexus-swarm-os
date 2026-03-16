/**
 * NEXUS CEREBRO E2E Tests - MissionControl
 * V12.1 RETINA: Tests for Swarm mode selection and workflow launch
 */
import { test, expect } from '@playwright/test';

// Helper to login before each test
async function login(page: import('@playwright/test').Page) {
  await page.goto('http://localhost:3000');
  await page.locator('#username').fill('admin');
  await page.locator('#password').fill('nexus');
  await page.getByRole('button', { name: /sign in/i }).click();
  await expect(page.getByRole('button', { name: /Hive Map/i })).toBeVisible({ timeout: 15000 });
}

test.describe('MissionControl Component', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('should display all 6 Swarm modes', async ({ page }) => {
    // Check MissionControl is visible
    await expect(page.getByText('Mission Control')).toBeVisible();

    // Verify all 6 modes are present
    const modes = ['PARALLEL', 'SEQUENTIAL', 'LEAD', 'PING', 'SPECIALIST', 'RED'];
    for (const mode of modes) {
      await expect(page.getByText(mode, { exact: false })).toBeVisible();
    }
  });

  test('should allow selecting different Swarm modes', async ({ page }) => {
    // Click on SEQUENTIAL mode
    await page.locator('[data-testid="mode-SEQUENTIAL"]').click();

    // Verify SEQUENTIAL is selected (has cyan border)
    const sequentialBtn = page.locator('[data-testid="mode-SEQUENTIAL"]');
    await expect(sequentialBtn).toHaveClass(/border-cyan/);
  });

  test('should show mode description on selection', async ({ page }) => {
    // Click on RED_BLUE mode
    await page.locator('[data-testid="mode-RED_BLUE"]').click();

    // Verify description appears
    await expect(page.getByText(/adversarial/i)).toBeVisible();
  });

  test('should have objective textarea', async ({ page }) => {
    // Find objective textarea
    const textarea = page.getByPlaceholder(/enter your task/i);
    await expect(textarea).toBeVisible();

    // Fill it
    await textarea.fill('Test mission objective');
    await expect(textarea).toHaveValue('Test mission objective');
  });

  test('should enable ENGAGE button when objective is filled', async ({ page }) => {
    // Initially ENGAGE should be disabled (no objective)
    const engageBtn = page.getByRole('button', { name: /engage/i });

    // Fill objective
    await page.getByPlaceholder(/enter your task/i).fill('Test objective');

    // ENGAGE should now be enabled
    await expect(engageBtn).toBeEnabled();
  });
});
