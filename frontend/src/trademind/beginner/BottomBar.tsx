// Phone bottom bar (bx7): one link per menu section, first page the viewer may open. Not mounted yet.
// Hidden on wide screens by beginner.css (.bx-bottombar shows under 640px only).
import { Link } from 'react-router-dom'

import { findSection, visiblePages, visibleSections } from '../menu'

export default function BottomBar({ isOwner, activePath }: { isOwner: boolean; activePath: string }) {
  const activeId = findSection(activePath)?.id
  return (
    <nav className="bx-bottombar" aria-label="Main sections">
      {visibleSections(isOwner).map((s) => {
        const first = visiblePages(s, isOwner)[0]
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
