import { NeoTradingViewWorkspace } from '@/components/neo-desk/NeoTradingViewWorkspace'
import { useAuthStore } from '@/stores/authStore'

export default function NeoTrading() {
  const account = useAuthStore((state) =>
    state.isAuthenticated ? (state.user?.username ?? null) : null
  )
  return <NeoTradingViewWorkspace key={account ?? 'signed-out'} />
}
