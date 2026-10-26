// Which money a Portfolio screen shows: practice (Paper) or the owner's real Zerodha account (Real).
// One place, so every Portfolio screen carries exactly one indicator and the wording cannot drift.
// Pure data and functions (tested); TradeMindApp.tsx renders the strip from it.

import { matches } from './menu'

export type BookKind = 'paper' | 'real'
export type Book = { kind: BookKind; name: string; note: string }

const BOOKS: { to: string; book: Book }[] = [
  {
    to: '/trademind/positions',
    book: {
      kind: 'paper',
      name: 'Bot (Paper)',
      note: 'Every figure on this screen is practice money from the bot\u2019s paper trading. No real money is involved.',
    },
  },
  {
    to: '/trademind/testing',
    book: {
      kind: 'paper',
      name: 'Testing (Paper)',
      note: 'Manual practice trades with their own practice money. Not the bot\u2019s book and not real money.',
    },
  },
  {
    to: '/trademind/manual-test',
    book: {
      kind: 'paper',
      name: 'Manual test (Paper)',
      note: 'Your own practice buys, kept in the Testing book. Not the bot\u2019s picks and not real money.',
    },
  },
  {
    to: '/trademind/holdings',
    book: {
      kind: 'real',
      name: 'My Zerodha (Real)',
      note: 'Real money in your Zerodha account. Actions on this screen can place real orders.',
    },
  },
  {
    to: '/trademind/portfolio',
    book: {
      kind: 'paper',
      name: 'Paper Overview',
      note: 'The bot\u2019s paper book only. Real holdings and testing trades are not included in these figures.',
    },
  },
]

/** The book a Portfolio screen shows, or undefined for any other screen. */
export function bookOf(path: string): Book | undefined {
  return BOOKS.find((b) => matches(path, b.to))?.book
}
