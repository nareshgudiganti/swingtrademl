// Warning shown on Settings when Zerodha is disconnected: stop-loss/target checks need live prices,
// so they are not running on ANY book. Each book is listed on its own and never added together
// (paper and real are never summed, tracker bx2/fx4). Real holdings must stay in this warning.

// The server sends only the books this caller may see (a tester gets testing alone), so any may be missing.
type BookCounts = { bot?: number; testing?: number; real?: number }

export function stopCheckWarning(
  brokerAuthenticated: boolean,
  openPositions: number | null | undefined,
  byBook?: BookCounts,
): string | null {
  if (brokerAuthenticated) return null
  // Older API without the per-book split: open_positions is the bot's own book.
  const books: BookCounts = byBook ?? { bot: openPositions ?? 0 }
  const parts: string[] = []
  if ((books.bot ?? 0) > 0) parts.push(`Bot (paper) ${books.bot}`)
  if ((books.testing ?? 0) > 0) parts.push(`Testing (paper) ${books.testing}`)
  if ((books.real ?? 0) > 0) parts.push(`My Holdings (real money) ${books.real}`)
  if (parts.length === 0) return null
  return `Stop-loss/target checks are NOT running on your open positions: ${parts.join(' · ')}.`
}
