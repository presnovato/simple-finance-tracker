// Считает отпечаток исходников TMA и пишет tma/dist/build-meta.json.
//
// Алгоритм обязан совпадать с finance_bot/services/bundle.py: sha256 по
// отсортированным путям относительно tma/ с LF-нормализацией содержимого.
//
// `vite build` очищает dist/, поэтому перед сборкой (`--prepare`) старый
// build-meta.json копируется в node_modules/.cache. После сборки, если
// source_hash не изменился, сохраняется прежний built_at — иначе каждый
// прогон делал бы tma/dist грязным и CI-проверка свежести всегда падала бы.

import { createHash } from 'node:crypto'
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const TMA_ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const META_PATH = join(TMA_ROOT, 'dist', 'build-meta.json')
const CACHE_PATH = join(
  TMA_ROOT,
  'node_modules',
  '.cache',
  'finance-tracker-build-meta.json',
)
const EXTRA_FILES = [
  'index.html',
  'package-lock.json',
  'vite.config.ts',
  'tsconfig.json',
  'tsconfig.app.json',
  'tsconfig.node.json',
]

function collectFiles(root) {
  const rels = []
  const walk = (rel) => {
    const abs = join(root, rel)
    for (const entry of readdirSync(abs)) {
      const childRel = `${rel}/${entry}`
      if (statSync(join(root, childRel)).isDirectory()) walk(childRel)
      else rels.push(childRel)
    }
  }
  walk('src')
  for (const extra of EXTRA_FILES) {
    if (existsSync(join(root, extra))) rels.push(extra)
  }
  return rels.sort()
}

function sourceHash(root) {
  const hash = createHash('sha256')
  for (const rel of collectFiles(root)) {
    const content = readFileSync(join(root, rel), 'utf8').replace(/\r\n/g, '\n')
    hash.update(rel, 'utf8')
    hash.update('\0')
    hash.update(content, 'utf8')
    hash.update('\0')
  }
  return hash.digest('hex')
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

if (process.argv.includes('--prepare')) {
  if (existsSync(META_PATH)) {
    mkdirSync(dirname(CACHE_PATH), { recursive: true })
    copyFileSync(META_PATH, CACHE_PATH)
  }
  process.exit(0)
}

const source_hash = sourceHash(TMA_ROOT)
let built_at = null
for (const candidate of [readJson(CACHE_PATH), readJson(META_PATH)]) {
  if (candidate && candidate.source_hash === source_hash && candidate.built_at) {
    built_at = candidate.built_at
    break
  }
}
if (!built_at) built_at = new Date().toISOString()

writeFileSync(
  META_PATH,
  JSON.stringify({ source_hash, built_at }, null, 2) + '\n',
)
