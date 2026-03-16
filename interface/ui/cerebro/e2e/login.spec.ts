import { test, expect } from '@playwright/test';

test.describe('CEREBRO Login Flow', () => {
  test('should login with admin/nexus and see Dashboard', async ({ page }) => {
    // Navigate to the app
    await page.goto('http://localhost:3000');

    // Should see login form - use id selectors
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#password')).toBeVisible();

    // Fill credentials
    await page.locator('#username').fill('admin');
    await page.locator('#password').fill('nexus');

    // Click login button
    await page.getByRole('button', { name: /sign in/i }).click();

    // Wait for navigation to dashboard - look for tab button
    await expect(page.getByRole('button', { name: /Hive Map/i })).toBeVisible({ timeout: 15000 });

    // Verify Mission Control is present
    await expect(page.getByText(/Mission Control/i)).toBeVisible();

    console.log('Login successful! Dashboard loaded with Mission Control.');
  });

  test('should show error with invalid credentials', async ({ page }) => {
    await page.goto('http://localhost:3000');

    // Wait for form to load
    await expect(page.locator('#username')).toBeVisible({ timeout: 10000 });

    // Fill wrong credentials
    await page.locator('#username').fill('wrong');
    await page.locator('#password').fill('wrong');

    // Click login
    await page.getByRole('button', { name: /sign in/i }).click();

    // Should show error message
    await expect(page.getByText(/invalid/i)).toBeVisible({ timeout: 10000 });
  });
});
