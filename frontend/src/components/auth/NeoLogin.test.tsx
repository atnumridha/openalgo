import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, it, vi } from 'vitest'
import { NeoLogin } from '@/components/auth/NeoLogin'

afterEach(() => vi.unstubAllGlobals())

it('submits only TOTP using the native CSRF-protected login route', async () => {
  const sent: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/auth/csrf-token')
        return new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
      sent.push(JSON.parse(String(init?.body)))
      expect(new Headers(init?.headers).get('X-CSRFToken')).toBe('fixture-csrf')
      return new Response(
        JSON.stringify({
          status: 'success',
          username: 'neo',
          broker: 'kotak',
          analyze_mode: true,
          api_key: 'fixture-openalgo-key',
        })
      )
    })
  )
  render(
    <MemoryRouter>
      <NeoLogin />
    </MemoryRouter>
  )
  expect(screen.queryByText('Flattrade')).not.toBeInTheDocument()
  expect(screen.queryByText('Separate broker connection')).not.toBeInTheDocument()
  expect(screen.queryByLabelText(/mobile|mpin|password|secret/i)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Authenticator TOTP'), { target: { value: '654321' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect Kotak' }))
  await waitFor(() => expect(sent).toEqual([{ totp: '654321' }]))
})

it('shows rejected authentication immediately and clears the submitted code', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/auth/csrf-token')
        return new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
      return new Response(
        JSON.stringify({ status: 'error', message: 'Retry with a fresh authenticator code.' }),
        { status: 400 }
      )
    })
  )
  render(
    <MemoryRouter>
      <NeoLogin />
    </MemoryRouter>
  )
  fireEvent.change(screen.getByLabelText('Authenticator TOTP'), { target: { value: '654321' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect Kotak' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Retry with a fresh authenticator code.'
  )
  expect(screen.getByLabelText('Authenticator TOTP')).toHaveValue('')
})

it('reuses a verified owner session without asking for a new TOTP', async () => {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      requests.push(url)
      if (url === '/auth/csrf-token')
        return new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
      return new Response(
        JSON.stringify({
          status: 'success',
          username: 'neo',
          broker: 'kotak',
          analyze_mode: true,
          api_key: 'fixture-openalgo-key',
        })
      )
    })
  )
  render(
    <MemoryRouter>
      <NeoLogin canResume />
    </MemoryRouter>
  )
  await waitFor(() => expect(requests).toContain('/auth/neo-resume'))
  expect(requests).not.toContain('/auth/neo-kotak-login')
})

it('sets the authoritative Sandbox mode before displaying the dashboard', async () => {
  const { useThemeStore } = await import('@/stores/themeStore')
  useThemeStore.getState().setAppMode('live')
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/auth/csrf-token')
        return new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
      return new Response(
        JSON.stringify({
          status: 'success',
          username: 'neo',
          broker: 'kotak',
          analyze_mode: true,
          api_key: 'fixture-openalgo-key',
        })
      )
    })
  )
  render(
    <MemoryRouter>
      <NeoLogin />
    </MemoryRouter>
  )
  fireEvent.change(screen.getByLabelText('Authenticator TOTP'), { target: { value: '654321' } })
  fireEvent.click(screen.getByRole('button', { name: 'Connect Kotak' }))
  await waitFor(() => expect(useThemeStore.getState().appMode).toBe('analyzer'))
})

it('keeps TOTP hidden while a verified browser resumes the saved session', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/auth/csrf-token'
        ? new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
        : new Promise<Response>(() => {})
    )
  )
  render(
    <MemoryRouter>
      <NeoLogin canResume />
    </MemoryRouter>
  )
  expect(screen.queryByLabelText('Authenticator TOTP')).not.toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(/saved.*session/i)
})
it('offers a saved-session retry after a service failure instead of asking for TOTP', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/auth/csrf-token'
        ? new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
        : new Response(
            JSON.stringify({
              status: 'error',
              message: 'Saved session validation is temporarily unavailable.',
              requires_totp: false,
            }),
            { status: 503 }
          )
    )
  )
  render(
    <MemoryRouter>
      <NeoLogin canResume />
    </MemoryRouter>
  )
  expect(await screen.findByRole('button', { name: 'Retry saved connection' })).toBeEnabled()
  expect(screen.queryByLabelText('Authenticator TOTP')).not.toBeInTheDocument()
})
it('shows only TOTP after the broker session is confirmed expired', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url === '/auth/csrf-token'
        ? new Response(JSON.stringify({ csrf_token: 'fixture-csrf' }))
        : new Response(
            JSON.stringify({
              status: 'error',
              message: 'Kotak session expired.',
              requires_totp: true,
            }),
            { status: 401 }
          )
    )
  )
  render(
    <MemoryRouter>
      <NeoLogin canResume />
    </MemoryRouter>
  )
  expect(await screen.findByLabelText('Authenticator TOTP')).toBeEnabled()
  expect(screen.queryByLabelText(/MPIN|Mobile|Secret/i)).not.toBeInTheDocument()
})
