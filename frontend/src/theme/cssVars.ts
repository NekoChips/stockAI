/** 读取 :root / [data-theme] 上的 CSS 变量，供 Canvas 绘制使用。 */
export function cssVar(name: string, fallback = ''): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function chartPalette() {
  return {
    subtle: cssVar('--subtle', '#64748B'),
    line: cssVar('--line', '#D8E2F0'),
    ink: cssVar('--ink', '#0F172A'),
    surface: cssVar('--surface', '#FFFFFF'),
    brand: cssVar('--brand', '#0F766E'),
    accent: cssVar('--accent', '#0369A1'),
    gain: cssVar('--gain', '#DC2626'),
    loss: cssVar('--loss', '#059669'),
    crosshair: cssVar('--chart-crosshair', '#8AA6CA'),
  };
}
