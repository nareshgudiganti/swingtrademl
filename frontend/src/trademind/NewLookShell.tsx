// The new look: a light app with a left sidebar (the owner's 2026-10-24 concept). It wraps the SAME pages, menu
// and route table as the classic look (useShell + TradeMindRoutes in TradeMindApp.tsx); only the frame and Today
// differ. Display only. "Classic look" at the foot of the sidebar switches back (see look.ts).
//
// The sidebar lists the five owner-approved sections (menu.ts). The open section shows its pages under it; on a
// phone the sidebar becomes a scrolling row at the top.

import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'

import './newlook.css'
import { logOut } from './AccountMenu'
import StockSearch from './beginner/StockSearch'
import { useLook } from './look'
import { splitLabel, visiblePages, type SectionId } from './menu'
import { OfflineBanner } from './PageState'
import PricesBadge from './PricesBadge'
import TopBarAlerts from './TopBarAlerts'
import { TradeMindRoutes, useShell } from './TradeMindApp'
import { Icon } from './ui'

const SECTION_ICON: Record<SectionId, ReactNode> = {
  today: <Icon.Pulse />,
  discover: <Icon.Search />,
  portfolio: <Icon.Layers />,
  insights: <Icon.Chart />,
  admin: <Icon.Shield />,
}

export default function NewLookShell({ ownerConsole }: { ownerConsole: boolean }) {
  const [, setLook] = useLook()
  const { canSeeRealAccount, seesAll, book, broker, sections, section, pages, showBook, paperButNotPaper, chip } =
    useShell(ownerConsole)
  const pageTitle = pages.length > 1 ? section.label : (pages[0]?.label ?? section.label)

  return (
    <div className="tm tm-new" data-look="new">
      <aside className="tmn-side" aria-label="Menu">
        <Link to="/trademind" className="tmn-logo">
          <span className="tm-logo-mark" />
          TradeMind
        </Link>
        <span className="tmn-practice" title="Everything here is paper trading">
          Practice
        </span>
        <nav className="tmn-nav" aria-label="Sections">
          {sections.map((sec) => {
            const secPages = visiblePages(sec, ownerConsole, { realAccount: canSeeRealAccount })
            const open = sec.id === section.id
            return (
              <div key={sec.id} className={`tmn-sec ${open ? 'open' : ''}`}>
                <Link to={secPages[0]!.to} className={`tmn-sec-link ${open ? 'active' : ''}`} data-testid={`nav-${sec.id}`}>
                  {SECTION_ICON[sec.id]}
                  <span>{sec.label}</span>
                </Link>
                {open && pages.length > 1 && (
                  <div className="tmn-pages" data-testid="subnav">
                    {pages.map((pg) => {
                      const { text, tag } = splitLabel(pg.label)
                      return (
                        <NavLink key={pg.to} to={pg.to} end={pg.end} className={({ isActive }) => (isActive ? 'active' : '')}>
                          {text}
                          {tag && <span className={`tmn-tag tmn-tag-${tag.toLowerCase()}`}>{tag}</span>}
                        </NavLink>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </nav>
        <div className="tmn-side-foot">
          <button
            type="button"
            className="tmn-switch"
            onClick={() => setLook('classic')}
            title="Go back to the classic dark look. Nothing else changes."
            data-testid="look-switch"
          >
            <Icon.Back /> Classic look
          </button>
          <button type="button" className="tmn-logout" onClick={logOut} title="Log out of this app">
            Log out
          </button>
        </div>
      </aside>

      <div className="tmn-main">
        <header className="tmn-top">
          <h1 className="tmn-title">{pageTitle}</h1>
          {(ownerConsole || seesAll) && <StockSearch />}
          <div className="tmn-top-right">
            <PricesBadge />
            {ownerConsole && broker.data && (
              <Link
                to="/trademind/control"
                className={`tm-zchip tm-zerodha-chip ${broker.data.broker_authenticated ? 'tm-zchip-ok' : ''}`}
                title="Open the control room"
              >
                {broker.data.broker_authenticated ? 'Zerodha connected' : 'Zerodha: not logged in'}
              </Link>
            )}
            {ownerConsole && <TopBarAlerts />}
            <span className={`tm-status-chip ${chip.ok ? 'tm-status-chip-ok' : ''}`} title={chip.title} data-testid="brain-chip">
              {chip.label}
            </span>
          </div>
        </header>
        {book && showBook && (
          <div className={`tm-bookstrip tm-bookstrip-${book.kind}`} data-testid="book-strip" data-book={book.kind}>
            <span className="tm-booktag">{book.kind === 'real' ? 'Real' : 'Paper'}</span>
            <span>
              <strong>{book.name}.</strong> {book.note}
              {paperButNotPaper && (
                <strong className="tm-neg"> Warning: the server is not in paper mode, so these figures may be real money.</strong>
              )}
            </span>
          </div>
        )}
        <OfflineBanner />
        <TradeMindRoutes
          ownerConsole={ownerConsole}
          testingOff={broker.data?.paper_tester_enabled === false}
          realAccount={canSeeRealAccount}
          look="new"
        />
      </div>
    </div>
  )
}
