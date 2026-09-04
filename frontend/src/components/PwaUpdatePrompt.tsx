import { useRegisterSW } from 'virtual:pwa-register/react'

// Mounted once, outside the auth gate, so the service worker registers (and
// the app becomes installable) whether or not the user is logged in yet.
// registerType is 'prompt' in vite.config.ts on purpose — a trading
// dashboard should never swap its running JS out from under a mid-session
// user, so we surface this banner instead of auto-reloading.
export default function PwaUpdatePrompt() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    offlineReady: [offlineReady, setOfflineReady],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisterError: (error) => {
      console.error('Service worker registration failed', error)
    },
  })

  if (!needRefresh && !offlineReady) return null

  const dismiss = () => {
    setNeedRefresh(false)
    setOfflineReady(false)
  }

  return (
    <div className="pwa-toast banner banner-info">
      {needRefresh ? (
        <>
          A new version is ready.{' '}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault()
              updateServiceWorker(true)
            }}
            style={{ color: 'inherit', textDecoration: 'underline' }}
          >
            Reload to update
          </a>
        </>
      ) : (
        'Ready to work offline.'
      )}
      <button className="pwa-toast-dismiss" onClick={dismiss} aria-label="Dismiss">
        ✕
      </button>
    </div>
  )
}
