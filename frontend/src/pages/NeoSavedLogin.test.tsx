import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import Login from './Login'
afterEach(() => vi.unstubAllGlobals())
it('requests only TOTP when the broker session is expired instead of redirecting to a falsely connected dashboard', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/auth/check-setup')
        return new Response(JSON.stringify({ saved_login_enabled: true, can_resume: true }))
      if (url === '/auth/session-status')
        return new Response(
          JSON.stringify({
            logged_in: true,
            broker: 'kotak',
            user: 'neo',
            broker_session_expired: true,
          })
        )
      if (url === '/auth/csrf-token')
        return new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
      if (url === '/auth/neo-resume')
        return new Response(
          JSON.stringify({
            status: 'error',
            message: 'Kotak session expired.',
            requires_totp: true,
          }),
          { status: 401 }
        )
      throw Error('Unexpected login request')
    })
  )
  render(
    <MemoryRouter initialEntries={['/login']}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<p>Connected dashboard</p>} />
      </Routes>
    </MemoryRouter>
  )
  expect(await screen.findByLabelText('Authenticator TOTP')).toBeVisible()
  expect(screen.queryByText('Connected dashboard')).not.toBeInTheDocument()
})
