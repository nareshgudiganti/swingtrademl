// One-off icon rasterizer. Run with: node scripts/generate-icons.mjs
// `sharp` is installed with --no-save specifically for this — it's not a
// runtime or build dependency, just a local tool to turn the SVG source into
// the PNGs the web manifest and iOS home-screen icon require.
import sharp from 'sharp'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const dir = path.dirname(fileURLToPath(import.meta.url))
const src = path.join(dir, 'icon-master.svg')
const outDir = path.join(dir, '..', 'public')

const targets = [
  { file: 'apple-touch-icon.png', size: 180 },
  { file: 'pwa-192.png', size: 192 },
  { file: 'pwa-512.png', size: 512 },
  { file: 'pwa-maskable-512.png', size: 512, padded: true },
  { file: 'favicon-32.png', size: 32 },
]

for (const t of targets) {
  const pipeline = sharp(src).resize(t.size, t.size)
  if (t.padded) {
    // Maskable icons need ~20% safe-zone padding so Android's mask shapes
    // don't clip the glyph — shrink the art into an 60%-sized canvas first.
    const inner = Math.round(t.size * 0.6)
    await sharp(src)
      .resize(inner, inner)
      .extend({
        top: Math.round((t.size - inner) / 2),
        bottom: Math.round((t.size - inner) / 2),
        left: Math.round((t.size - inner) / 2),
        right: Math.round((t.size - inner) / 2),
        background: '#3f6fd9',
      })
      .png()
      .toFile(path.join(outDir, t.file))
  } else {
    await pipeline.png().toFile(path.join(outDir, t.file))
  }
  console.log('wrote', t.file)
}
