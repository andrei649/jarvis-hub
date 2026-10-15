import { describe, expect, it } from 'vitest';
import type { Report } from '../api/business';
import { csvCell, reportCsv, visibleReportRows } from './business-export';

const report: Report = {
  id: 'r1', workflow_id: 'sales_overview', title: 'Vânzări', summary: 'Rezumat',
  metrics: { paid_orders: 1 }, rows: [{ name: 'Alpha', amount: 1 }],
  coverage: [{ source: 'CSV', synced_at: null, description: 'import', complete: true }],
  warnings: ['Parțial'], created_at: '2026-10-14T10:00:00Z',
  filters: { start_date: '2026-10-01', end_date: '2026-10-13' },
  source_selection: { connection_id: 'csv1' },
};

describe('business report export', () => {
  it('quotes commas, quotes and newlines and neutralizes formulas after whitespace', () => {
    expect(csvCell('a,"b"\nc')).toBe('"a,""b""\nc"');
    for (const value of ['=1+1', ' +1', '\t-1', '\n@SUM(A1)', '\uFEFF=CMD', '\u0000=1', '\u0007@SUM(A1)', '\u007f+1']) {
      expect(csvCell(value)).toBe(`"'${value}"`);
    }
  });

  it('exports only the 100 visible rows with metadata, coverage and warnings', () => {
    const many = { ...report, rows: Array.from({ length: 105 }, (_, index) => ({ name: index === 0 ? '=SUM(A1)' : `row-${index}`, amount: index })) };
    expect(visibleReportRows(many)).toHaveLength(100);
    const csv = reportCsv(many);
    expect(csv).toContain('"De la data (UTC)","2026-10-01"');
    expect(csv).toContain('"Avertisment","Parțial"');
    expect(csv).toContain('"Acoperire"');
    expect(csv).toContain('"name","amount"');
    expect(csv).toContain('"\'=SUM(A1)"');
    expect(csv).toContain('"row-99"');
    expect(csv).not.toContain('"row-100"');
  });
});
