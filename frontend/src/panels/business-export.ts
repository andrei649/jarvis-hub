import type { Report } from '../api/business';

export const VISIBLE_REPORT_ROWS = 100;

export function visibleReportRows(report: Report): Record<string, unknown>[] {
  return (report.rows || []).slice(0, VISIBLE_REPORT_ROWS);
}

function cellValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function csvCell(value: unknown): string {
  const raw = cellValue(value);
  // Spreadsheet programs may evaluate formulas after leading whitespace.
  const safe = /^[\s\u0000-\u001f\u007f\uFEFF]*[=+\-@]/u.test(raw) ? `'${raw}` : raw;
  return `"${safe.replace(/"/g, '""')}"`;
}

function csvLine(values: unknown[]): string {
  return values.map(csvCell).join(',');
}

export function reportCsv(report: Report): string {
  const rows = visibleReportRows(report);
  const lines = [
    csvLine(['Metadate raport', 'Valoare']),
    csvLine(['Titlu', report.title]),
    csvLine(['ID raport', report.id]),
    csvLine(['Tip raport', report.workflow_id]),
    csvLine(['Creat la', report.created_at]),
    csvLine(['Rezumat', report.summary]),
    csvLine(['Sursă selectată', report.source_selection?.connection_id || 'Toate sursele']),
    csvLine(['De la data (UTC)', report.filters?.start_date || 'Toate datele']),
    csvLine(['Până la data (UTC)', report.filters?.end_date || 'Toate datele']),
    csvLine(['Limită rânduri vizibile', VISIBLE_REPORT_ROWS]),
    csvLine(['Rânduri în CSV', rows.length]),
    ...Object.entries(report.metrics || {}).map(([key, value]) => csvLine([`Indicator: ${key}`, value])),
    ...(report.coverage || []).map((source) => csvLine(['Acoperire', JSON.stringify(source)])),
    ...(report.warnings || []).map((warning) => csvLine(['Avertisment', warning])),
    '',
  ];
  if (rows.length) {
    const columns = Object.keys(rows[0]);
    lines.push(csvLine(columns));
    lines.push(...rows.map((row) => csvLine(columns.map((key) => row[key]))));
  }
  return lines.join('\r\n') + '\r\n';
}

export function downloadReport(report: Report, format: 'json' | 'csv'): void {
  const body = format === 'json' ? JSON.stringify(report, null, 2) : reportCsv(report);
  const blob = new Blob([body], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `raport-business-${report.id.replace(/[^a-zA-Z0-9_-]/g, '_')}.${format}`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
