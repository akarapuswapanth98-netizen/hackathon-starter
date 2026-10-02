import { useEffect, useState } from 'react'
import Home from './pages/Home'
import FoodBridge from './pages/FoodBridge'

function currentRoute() {
  try {
    if (typeof window === 'undefined') return '/'
    const hash = window.location.hash || ''
    if (hash === '#/foodbridge' || hash.startsWith('#/foodbridge')) return '/foodbridge'
    if (window.location.pathname === '/foodbridge' || window.location.pathname.endsWith('/foodbridge')) return '/foodbridge'
  } catch { /* ignore */ }
  return '/'
}

export default function App() {
  const [route, setRoute] = useState(currentRoute())

  useEffect(() => {
    const onChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onChange)
    window.addEventListener('popstate', onChange)
    return () => {
      window.removeEventListener('hashchange', onChange)
      window.removeEventListener('popstate', onChange)
    }
  }, [])

  if (route === '/foodbridge') return <FoodBridge />
  return <Home />
}
