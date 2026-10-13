import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'

export function NeoLogin({ canResume = false }: { canResume?: boolean }) {
  const navigate = useNavigate()
  const login = useAuthStore((s) => s.login)
  const [totp, setTotp] = useState('')
  const [busy, setBusy] = useState(canResume)
  const [error, setError] = useState('')
  const attemptedResume = useRef(false)

  const connect = useCallback(
    async (resume: boolean, code = '') => {
      setBusy(true)
      setError('')
      try {
        const csrf = await fetchCSRFToken()
        if (!csrf) throw new Error('Local session unavailable')
        const response = await fetch(resume ? '/auth/neo-resume' : '/auth/neo-kotak-login', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
          body: JSON.stringify(resume ? {} : { totp: code }),
        })
        const data = await response.json()
        if (!response.ok || data.status !== 'success') {
          setError(data.message || 'Kotak login did not complete. Retry with a fresh code.')
          return
        }
        let analyzeMode = data.analyze_mode
      if (typeof analyzeMode !== 'boolean') {
        const modeResponse = await fetch('/auth/analyzer-mode', { credentials: 'include' })
        const modeData = await modeResponse.json()
        analyzeMode = modeData.data?.analyze_mode
        if (!modeResponse.ok || typeof analyzeMode !== 'boolean') {
          setError('Could not confirm the trading mode. Refresh the terminal before continuing.')
          return
        }
      }
      useThemeStore.getState().setAppMode(analyzeMode ? 'analyzer' : 'live')
      if (typeof data.api_key === 'string') useAuthStore.getState().setApiKey(data.api_key)
      login(data.username, data.broker || 'kotak')
        navigate('/dashboard', { replace: true })
      } catch {
        setError('Could not connect to the local terminal. Refresh the page and retry.')
      } finally {
        setTotp('')
        setBusy(false)
      }
    },
    [login, navigate]
  )

  useEffect(() => {
    if (canResume && !attemptedResume.current) {
      attemptedResume.current = true
      void connect(true)
    }
  }, [canResume, connect])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Connect Kotak Neo</CardTitle>
          <CardDescription>
            Your account details are configured privately. Use your authenticator only when a new
            login is required.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <Alert variant="destructive" role="alert" className="mb-4">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (!busy && /^\d{6}$/.test(totp)) void connect(false, totp)
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="neo-totp">Authenticator TOTP</Label>
              <Input
                id="neo-totp"
                type="password"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                pattern="[0-9]{6}"
                value={totp}
                disabled={busy}
                onChange={(event) => setTotp(event.target.value.replace(/\D/g, '').slice(0, 6))}
                required
              />
            </div>
            <Button className="w-full" type="submit" disabled={busy || totp.length !== 6}>
              {busy ? 'Connecting Kotak…' : 'Connect Kotak'}
            </Button>
            <p className="text-sm text-muted-foreground">
              Strategy activation is controlled separately from login.
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
