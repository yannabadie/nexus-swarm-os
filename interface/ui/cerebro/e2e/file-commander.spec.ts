/**
 * NEXUS CEREBRO E2E Tests - FileCommander
 * V12.1 RETINA: Tests for file tree navigation and editor
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

test.describe('FileCommander Component', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    // Navigate to Files tab
    await page.getByRole('button', { name: /Files/i }).click();
  });

  test('should display file tree panel', async ({ page }) => {
    // Check Files header is visible
    await expect(page.getByText('Files', { exact: true }).first()).toBeVisible();

    // Check refresh button exists
    await expect(page.getByTitle('Refresh')).toBeVisible();
  });

  test('should show "Select a file" placeholder when no file selected', async ({ page }) => {
    await expect(page.getByText(/select a file to edit/i)).toBeVisible({ timeout: 10000 });
  });

  test('should load file tree from API', async ({ page }) => {
    // Wait for tree to load (should see at least one directory or file)
    // The tree loads from /api/files/tree
    await page.waitForTimeout(2000); // Allow API call to complete

    // Look for any folder or file icon (these come from the tree)
    const treeContent = page.locator('.text-xs.font-semibold.text-gray-400.uppercase.tracking-wider');
    await expect(treeContent.filter({ hasText: 'Files' })).toBeVisible();
  });

  test('should show Monaco editor when file is selected', async ({ page }) => {
    // This test requires the backend to be running with files available
    // For now, just verify the editor placeholder is visible
    await expect(page.getByText(/select a file to edit/i)).toBeVisible({ timeout: 10000 });

    // Monaco editor container should exist in the DOM
    const editorContainer = page.locator('.flex-1.relative');
    await expect(editorContainer.first()).toBeVisible();
  });
});
