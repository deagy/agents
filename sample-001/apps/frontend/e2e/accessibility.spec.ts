import { expect, test } from '@playwright/test'

test('anonymous workspace is keyboard operable at a narrow viewport', async ({ page }) => {
  await page.route('**/api/v1/session', (route) => route.fulfill({ status: 401 }))
  await page.setViewportSize({ width: 320, height: 720 })
  await page.goto('/')
  const signIn = page.getByRole('link', { name: 'Sign in securely' })
  await expect(signIn).toBeVisible()
  await page.keyboard.press('Tab')
  await expect(signIn).toBeFocused()
  await expect(page.getByRole('status')).toContainText('Sign in')
})

test('clean documents alone expose a download action', async ({ page }) => {
  await page.route('**/api/v1/session', (route) => route.fulfill({ json: { authenticated: true, csrf_token: 'csrf', user: { display_name: 'Ada' } } }))
  await page.route('**/api/v1/documents', (route) => route.fulfill({ status: 201, json: { document: { id: 'doc', name: 'safe.pdf', status: 'clean' } } }))
  await page.goto('/')
  await page.getByLabel(/Choose a PDF/).setInputFiles({ name: 'safe.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-safe') })
  await page.getByRole('button', { name: 'Upload for scanning' }).click()
  await expect(page.getByRole('link', { name: 'Download clean document' })).toBeVisible()
})
