/**
 * NEXUS CEREBRO E2E Tests - Dashboard Responsive Layout
 * V12.1 RETINA: Tests for responsive design on mobile and desktop
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

test.describe('Dashboard Responsive Layout', () => {
  test('Desktop: should show sidebar with MissionControl and EventStream', async ({ page }) => {
    // Set desktop viewport
    await page.setViewportSize({ width: 1280, height: 720 });
    await login(page);

    // MissionControl should be visible in sidebar
    await expect(page.getByText('Mission Control').first()).toBeVisible();

    // EventStream should be visible in sidebar
    await expect(page.getByText('Event Stream').first()).toBeVisible();
  });

  test('Desktop: should NOT show Events tab (sidebar has EventStream)', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await login(page);

    // Events tab should be hidden on desktop (mobileOnly)
    const eventsTab = page.getByRole('button', { name: /^Events$/i });
    await expect(eventsTab).not.toBeVisible();
  });

  test('Mobile: should show collapsible MissionControl', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 667 });
    await login(page);

    // Should see collapsible MissionControl header
    const mcButton = page.getByText('Mission Control').first();
    await expect(mcButton).toBeVisible();

    // Click to expand
    await mcButton.click();

    // Should see Swarm Mode label after expansion
    await expect(page.getByText('Swarm Mode')).toBeVisible({ timeout: 5000 });
  });

  test('Mobile: should show Events tab', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await login(page);

    // Events tab should be visible on mobile
    const eventsTab = page.getByRole('button', { name: /Events/i });
    await expect(eventsTab).toBeVisible();

    // Click Events tab
    await eventsTab.click();

    // Should see EventStream content
    await expect(page.getByText('Event Stream')).toBeVisible();
  });

  test('Mobile: tabs should show short labels', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await login(page);

    // Should see short labels like "Hive" instead of "Hive Map"
    await expect(page.getByRole('button', { name: 'Hive' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Files' })).toBeVisible();
  });
});
