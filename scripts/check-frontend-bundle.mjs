import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const repoRoot = path.resolve(import.meta.dirname, '..');
const frontendRoot = path.resolve(repoRoot, 'frontend');
const assetsRoot = path.resolve(frontendRoot, '../src/stock_ai_agent/spa/assets');
const budgetPath = path.resolve(frontendRoot, 'bundle-budget.json');
const budget = JSON.parse(readFileSync(budgetPath, 'utf8'));

const jsFiles = readdirSync(assetsRoot)
  .filter((file) => file.endsWith('.js'))
  .map((file) => ({
    file,
    bytes: statSync(path.join(assetsRoot, file)).size,
  }));

if (!jsFiles.length) {
  console.error(`[bundle-budget] no JavaScript assets found in ${assetsRoot}`);
  process.exit(1);
}

const entry = jsFiles.find(({ file }) => /^index-[^/]+\.js$/.test(file));
if (!entry) {
  console.error('[bundle-budget] Vite entry chunk was not found.');
  process.exit(1);
}

const initial = jsFiles.filter(({ file }) =>
  /^(index|react-vendor|query-vendor|dayjs-vendor)-[^/]+\.js$/.test(file),
);
const dashboardRoute = jsFiles.filter(({ file }) =>
  /^(index|react-vendor|query-vendor|dayjs-vendor|DashboardPage|dashboard|client|format|cssVars)-[^/]+\.js$/.test(
    file,
  ),
);
const lazy = jsFiles.filter(({ file }) => !initial.some((asset) => asset.file === file));
const totalBytes = jsFiles.reduce((sum, asset) => sum + asset.bytes, 0);
const initialBytes = initial.reduce((sum, asset) => sum + asset.bytes, 0);
const dashboardRouteBytes = dashboardRoute.reduce((sum, asset) => sum + asset.bytes, 0);
const maxLazy = lazy.reduce((max, asset) => Math.max(max, asset.bytes), 0);

const kb = (bytes) => bytes / 1024;
const violations = [];
if (kb(entry.bytes) > budget.entryJsMaxKb) {
  violations.push(`entry ${entry.file} ${kb(entry.bytes).toFixed(1)} KB > ${budget.entryJsMaxKb} KB`);
}
if (kb(initialBytes) > budget.initialJsMaxKb) {
  violations.push(`initial JS ${kb(initialBytes).toFixed(1)} KB > ${budget.initialJsMaxKb} KB`);
}
if (kb(dashboardRouteBytes) > budget.dashboardRouteJsMaxKb) {
  violations.push(
    `dashboard route JS ${kb(dashboardRouteBytes).toFixed(1)} KB > ${budget.dashboardRouteJsMaxKb} KB`,
  );
}
if (kb(maxLazy) > budget.lazyChunkMaxKb) {
  const largest = lazy.reduce((current, asset) => (asset.bytes > current.bytes ? asset : current), lazy[0]);
  violations.push(`largest lazy chunk ${largest.file} ${kb(maxLazy).toFixed(1)} KB > ${budget.lazyChunkMaxKb} KB`);
}
if (kb(totalBytes) > budget.totalJsMaxKb) {
  violations.push(`total JS ${kb(totalBytes).toFixed(1)} KB > ${budget.totalJsMaxKb} KB`);
}

console.log(
  `[bundle-budget] entry ${kb(entry.bytes).toFixed(1)} KB; initial ${kb(initialBytes).toFixed(1)} KB; ` +
    `dashboard route ${kb(dashboardRouteBytes).toFixed(1)} KB; largest lazy ${kb(maxLazy).toFixed(1)} KB; ` +
    `total ${kb(totalBytes).toFixed(1)} KB`,
);

if (violations.length) {
  console.error('[bundle-budget] FAILED');
  violations.forEach((violation) => console.error(`- ${violation}`));
  process.exit(1);
}

console.log('[bundle-budget] passed');
