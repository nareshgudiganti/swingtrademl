# ev15: stock split for Phase B (locked)

Evidence plan section 3: the never-used stocks are split once, before the first Phase B run
(9 Nov 2026), so no one can pick the split after seeing results.

- **Reject set (129 stocks)**: never used to train any candidate. Used only for
  the robustness check, which can reject a candidate but never confirm one.
- **Extra training set (128 stocks)**: used only by candidate B2
  (trains on the 49 + these 128 = 177 stocks, scored on the same 49).
- The 49 stocks the model already uses are not part of the split.

| Item | Value |
|---|---|
| Population | 257 never-used stocks |
| Seed | 7 (project standard seed; the plan names none for this split) |
| Random generator | Python random.Random (Mersenne Twister), shuffle |
| Algorithm | population sorted alphabetically by symbol; copy shuffled with Python random.Random(7).shuffle; first 129 = reject_set, remaining 128 = extra_training_set; each list then stored sorted |
| Source | Local database (daily candles to 2026-09-08). used_49 = instruments with is_active and is_watchlisted (the walk_forward universe). population = active instruments with segment NSE, instrument_type EQ and at least one 'day' candle, minus used_49. Index series (segment INDICES) excluded. Matches the 306 = 49 + 257 count in docs/brain/evidence/wider_universe_data_check_2026-10-12.md. used_49 also equals every watchlist_snapshots day (2026-10-05..2026-10-16). Read on 2026-10-21 with the same filters as load_from_db (SQL: is_active and segment='NSE' and instrument_type='EQ' and exists a 'day' candle, minus is_active and is_watchlisted). |
| File | `stock_split_ev15.json` |
| SHA-256 of file | `bc8878f24a730f4b8831914280085ed3ef22ef77959dfd47c00de654362c78b3` |

Reproduce: `backend/tests/test_stock_split.py` recomputes the split from the committed population and
checks it against the lists and this hash. Do not edit or regenerate the JSON: any change breaks the
hash and the test, which is the point.
