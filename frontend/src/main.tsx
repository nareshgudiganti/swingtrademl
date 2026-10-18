import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import App from './App'
import PwaUpdatePrompt from './components/PwaUpdatePrompt'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Market data moves; 30s keeps the dashboard live without hammering the
      // API on every focus change.
      staleTime: 30_000,
      refetchInterval: 60_000,
      refetchOnWindowFocus: true,
      retry: 1,
      // Keep loaded answers in memory for 30 minutes (react-query's default is 5) so a slow or dropped
      // connection, or going back to a screen, still shows the last data with its time instead of a blank page.
      gcTime: 30 * 60_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
      <PwaUpdatePrompt />
    </QueryClientProvider>
  </StrictMode>,
)
