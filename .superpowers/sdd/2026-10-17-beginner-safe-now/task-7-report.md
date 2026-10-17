# Task 7 report (bx7 search + bottom bar)
Files (new): frontend/src/trademind/beginner/{StockSearch.tsx,BottomBar.tsx,StockSearch.test.tsx,BottomBar.test.tsx}; appended CSS to beginner.css.
RED: both test files failed "Failed to load url ./StockSearch" (modules absent), 2 files failed, no tests ran.
GREEN: npx vitest run -> 8 files, 135 tests passed; npx tsc --noEmit -p . clean.
(One test-only regex slip for aria-current attribute order was fixed in the test, not the component.)
Design: StockSearchView pure (query, results, loading, onQuery, onPick); StockSearch wrapper = 250ms debounce + useQuery(api.instruments) only when trimmed >=2 chars + navigate(stockUrl). Exports stockUrl, pickIndex. Arrow keys + Enter. BottomBar uses visibleSections/visiblePages/findSection from menu.ts (5 owner / 4 others); CSS shows it only under 640px.
Not mounted anywhere; no files outside beginner/ touched.
