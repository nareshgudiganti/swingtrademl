// Which backend calls do the classic screens make that no TradeMind page makes?
// A reproducible SAFETY CHECK, not proof of feature parity (the browser-level check in the design spec, section 6,
// Part B, is also required before any classic screen is deleted).
// Every gap must be explained in classic-parity-allowlist.json; the Phase 6 deletion gate (--strict) also refuses
// anything still only "planned", "keep" or "decide".
// Usage: node scripts/classic-parity.mjs [--check] [--strict] [--json]
//
// What it reads: `api.name` written in a page, plus in the local modules that page imports directly (one level:
// shared components, lib, hooks; the api client itself is not followed). Comments are ignored. Ways of using `api`
// it cannot read (api['x'], const { x } = api, passing api as a value) are reported as an unreadable-access gap.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const CALL = /\bapi\.([A-Za-z0-9_]+)/g
const DYNAMIC = [
  ['api[...] access', /\bapi\s*\[/],
  ['destructuring from api', /\{[^{}]*\}\s*=\s*api\b/],
  ['api passed or aliased as a value', /(?:=|\(|,)\s*api\s*(?:;|,|\)|$)/m],
]
const IMPORT = /\bfrom\s+['"](\.{1,2}\/[^'"]+)['"]|\bimport\s*\(\s*['"](\.{1,2}\/[^'"]+)['"]\s*\)/g
const SOURCE = /\.(?:tsx?|mjs)$/
const DYNAMIC_CALL = '<dynamic api access>'
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

// Remove comments so a mention of api.x in a comment is not taken for a call. A "//" right after a colon (a URL),
// a quote or a backslash is left alone. Not a parser: it errs towards keeping text.
export function stripComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:\'"`])\/\/.*$/gm, '$1')
}

function resolveLocal(file, spec) {
  const base = path.resolve(path.dirname(file), spec)
  const candidates = [base, `${base}.tsx`, `${base}.ts`, `${base}.mjs`, path.join(base, 'index.tsx'), path.join(base, 'index.ts')]
  return candidates.find((c) => fs.existsSync(c) && fs.statSync(c).isFile() && SOURCE.test(c)) ?? null
}

function callsOf(file, srcDir) {
  const calls = new Set()
  const dynamic = []
  const scan = (f, label) => {
    const code = stripComments(fs.readFileSync(f, 'utf8'))
    for (const m of code.matchAll(CALL)) calls.add(m[1])
    for (const [name, re] of DYNAMIC) if (re.test(code)) dynamic.push(`${label}: ${name}`)
    return code
  }
  const own = scan(file, path.basename(file))
  const apiDir = path.join(srcDir, 'api') + path.sep
  for (const m of own.matchAll(IMPORT)) {
    const target = resolveLocal(file, m[1] ?? m[2])
    if (target && target !== file && !target.startsWith(apiDir)) {
      scan(target, path.relative(srcDir, target).split(path.sep).join('/'))
    }
  }
  return { calls, dynamic }
}

export function computeParity(srcDir) {
  const pagesDir = path.join(srcDir, 'pages')
  const trademind = new Set()
  for (const f of walk(path.join(srcDir, 'trademind')).filter((f) => /\.tsx?$/.test(f))) {
    for (const c of callsOf(f, srcDir).calls) trademind.add(c)
  }
  return fs
    .readdirSync(pagesDir)
    .filter((f) => f.endsWith('.tsx'))
    .sort()
    .map((f) => {
      const file = path.join(pagesDir, f)
      const { calls: found, dynamic } = callsOf(file, srcDir)
      const calls = [...found].sort()
      return {
        page: f.replace(/\.tsx$/, ''),
        lines: fs.readFileSync(file, 'utf8').split('\n').length,
        calls,
        gaps: calls.filter((c) => !trademind.has(c)),
        dynamic,
      }
    })
}

export function checkAllowlist(parity, allowlist, { strict = false } = {}) {
  const unexplained = []
  const planned = []
  for (const row of parity) {
    const entries = allowlist[row.page] ?? {}
    // Access this script cannot read is a blind spot: it is explained like a gap, never ignored.
    if ((row.dynamic ?? []).length > 0) {
      const e = entries[DYNAMIC_CALL] ?? entries['*']
      if (!e || !EXPLAINED.has(e.status)) unexplained.push({ page: row.page, call: DYNAMIC_CALL })
    }
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
    for (const r of parity) {
      const unreadable = r.dynamic.length ? ` | UNREADABLE api use: ${r.dynamic.join('; ')}` : ''
      console.log(`${r.page.padEnd(16)} ${String(r.lines).padStart(5)} lines ${String(r.calls.length).padStart(3)} calls | gaps: ${r.gaps.join(', ') || 'none'}${unreadable}`)
    }
    console.log(`\nunexplained: ${result.unexplained.length}  planned: ${result.planned.length}  strict: ${strict}  => ${result.ok ? 'OK' : 'FAIL'}`)
    for (const u of result.unexplained) console.log(`  unexplained: ${u.page}.${u.call}`)
    if (strict) for (const p of result.planned) console.log(`  still ${p.status}: ${p.page}.${p.call} (${p.task})`)
  }
  if (process.argv.includes('--check') || strict) process.exit(result.ok ? 0 : 1)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
