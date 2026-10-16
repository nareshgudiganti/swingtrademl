// Which backend calls do the classic screens make that no TradeMind page makes?
// A reproducible check, not a judgement: every gap must be explained in classic-parity-allowlist.json,
// and the Phase 6 deletion gate (--strict) also refuses anything still only "planned".
// Usage: node scripts/classic-parity.mjs [--check] [--strict] [--json]

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const CALL = /\bapi\.([A-Za-z0-9_]+)/g
const EXPLAINED = new Set(['v2', 'deferred', 'separate_app', 'planned', 'keep', 'decide'])
// Statuses that are not final: the deletion gate (--strict) refuses them.
const NOT_FINAL = new Set(['planned', 'decide', 'keep'])

function walk(dir) {
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name)
    return e.isDirectory() ? walk(full) : [full]
  })
}

function callsIn(file) {
  return new Set([...fs.readFileSync(file, 'utf8').matchAll(CALL)].map((m) => m[1]))
}

export function computeParity(srcDir) {
  const pagesDir = path.join(srcDir, 'pages')
  const trademind = new Set()
  for (const f of walk(path.join(srcDir, 'trademind')).filter((f) => /\.tsx?$/.test(f))) {
    for (const c of callsIn(f)) trademind.add(c)
  }
  return fs
    .readdirSync(pagesDir)
    .filter((f) => f.endsWith('.tsx'))
    .sort()
    .map((f) => {
      const file = path.join(pagesDir, f)
      const calls = [...callsIn(file)].sort()
      return {
        page: f.replace(/\.tsx$/, ''),
        lines: fs.readFileSync(file, 'utf8').split('\n').length,
        calls,
        gaps: calls.filter((c) => !trademind.has(c)),
      }
    })
}

export function checkAllowlist(parity, allowlist, { strict = false } = {}) {
  const unexplained = []
  const planned = []
  for (const row of parity) {
    const entries = allowlist[row.page] ?? {}
    for (const call of row.gaps) {
      const e = entries[call] ?? entries['*']
      if (!e || !EXPLAINED.has(e.status)) unexplained.push({ page: row.page, call })
      else if (NOT_FINAL.has(e.status)) planned.push({ page: row.page, call, task: e.task ?? '', status: e.status })
      else if ((e.status === 'v2' || e.status === 'deferred') && !e.decision) unexplained.push({ page: row.page, call })
    }
  }
  return { unexplained, planned, ok: unexplained.length === 0 && !(strict && planned.length > 0) }
}

function main() {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const parity = computeParity(path.join(here, '..', 'src'))
  const allow = JSON.parse(fs.readFileSync(path.join(here, 'classic-parity-allowlist.json'), 'utf8'))
  const strict = process.argv.includes('--strict')
  const result = checkAllowlist(parity, allow, { strict })
  if (process.argv.includes('--json')) console.log(JSON.stringify({ parity, ...result }, null, 2))
  else {
    for (const r of parity) console.log(`${r.page.padEnd(16)} ${String(r.lines).padStart(5)} lines ${String(r.calls.length).padStart(3)} calls | gaps: ${r.gaps.join(', ') || 'none'}`)
    console.log(`\nunexplained: ${result.unexplained.length}  planned: ${result.planned.length}  strict: ${strict}  => ${result.ok ? 'OK' : 'FAIL'}`)
    for (const u of result.unexplained) console.log(`  unexplained: ${u.page}.${u.call}`)
    if (strict) for (const p of result.planned) console.log(`  still planned: ${p.page}.${p.call} (${p.task})`)
  }
  if (process.argv.includes('--check') || strict) process.exit(result.ok ? 0 : 1)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
