// The owner's account menu (the person icon in the top bar): the Admin pages, then Log out as the last item.
// Log out sits here rather than on the bar itself so the bar stays on one line. Display only.
import { Link } from 'react-router-dom'

import { clearToken } from '../api/client'
import type { Page } from './menu'

/** Sign out of this app: forget the saved sign-in and go back to the start (the sign-in screen). */
export function logOut(): void {
  clearToken()
  window.location.assign('/')
}

export function AccountMenuList({
  pages,
  onLogOut = logOut,
  onNewLook,
}: {
  pages: Page[]
  onLogOut?: () => void
  /** The owner's way into the new look (look.ts): kept in this menu so the top bar keeps its room. */
  onNewLook?: () => void
}) {
  return (
    <div className="tm-menu-list" role="menu">
      {pages.map((pg) => (
        <Link key={pg.to} to={pg.to} role="menuitem">
          {pg.label}
        </Link>
      ))}
      {onNewLook && (
        <button type="button" role="menuitem" className="tm-menu-logout" onClick={onNewLook} data-testid="look-switch">
          Try the new look
        </button>
      )}
      <button type="button" role="menuitem" className="tm-menu-logout" title="Log out of this app" onClick={onLogOut}>
        Log out
      </button>
    </div>
  )
}
