// Phone bottom bar (bx7): one link per menu section, first page the viewer may open. NOT mounted: left unwired
// until the owner decides the phone layout (PR #55). If mounted, it is meant to replace the top row on a phone.
// Hidden on wide screens by beginner.css (.bx-bottombar shows under 640px only, where it replaces the top row).
import { Link } from 'react-router-dom'

import { resolveSection, visiblePages, visibleSections } from '../menu'
import './beginner.css'

type Props = { isOwner: boolean; activePath: string; realAccount?: boolean }

export default function BottomBar({ isOwner, activePath, realAccount = false }: Props) {
  // The same section the top bar highlights (a non-owner on an owner-only URL gets Today).
  const activeId = resolveSection(activePath, isOwner).id
  return (
    <nav className="bx-bottombar" aria-label="Main sections">
      {visibleSections(isOwner).map((s) => {
        const first = visiblePages(s, isOwner, { realAccount })[0]
        if (!first) return null
        const active = s.id === activeId
        return (
          <Link key={s.id} to={first.to} className={active ? 'bx-tab bx-active' : 'bx-tab'} aria-current={active ? 'page' : undefined}>
            {s.label}
          </Link>
        )
      })}
    </nav>
  )
}
