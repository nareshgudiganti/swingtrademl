// Shared TradeMind types (the sample data that used to live beside them is gone).

export type Action = 'TRADE' | 'WATCH' | 'WAIT' | 'AVOID'

export type Point = { t: string; v: number }

export type CandleBar = { t: string; o: number; h: number; l: number; c: number; vol: number }
