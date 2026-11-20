/** Parses RFC 4180-style CSV without a dependency. */

function stripBom(input: string): string {
  return input.charCodeAt(0) === 0xfeff ? input.slice(1) : input;
}

/** Rows of fields; quoted commas, escaped quotes, CRLF, and embedded newlines work. */
export function parseCsv(input: string): string[][] {
  const text = stripBom(input);
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  let index = 0;

  const endField = (): void => {
    row.push(field);
    field = '';
  };
  const endRow = (): void => {
    endField();
    rows.push(row);
    row = [];
  };

  while (index < text.length) {
    const character = text[index] ?? '';
    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 2;
          continue;
        }
        quoted = false;
        index += 1;
        continue;
      }
      field += character;
      index += 1;
      continue;
    }
    if (character === '"') {
      quoted = true;
      index += 1;
      continue;
    }
    if (character === ',') {
      endField();
      index += 1;
      continue;
    }
    if (character === '\n' || character === '\r') {
      endRow();
      index += character === '\r' && text[index + 1] === '\n' ? 2 : 1;
      continue;
    }
    field += character;
    index += 1;
  }
  if (field !== '' || row.length > 0) endRow();
  return rows;
}

const NUMERIC_CELL = /^[+\-−]?[\d,]+(?:\.\d+)?(?:\s*(?:%|％|元|倍|万|亿|股|手))?$/;

export function isNumericCell(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed === '') return false;
  return NUMERIC_CELL.test(trimmed);
}

/** Column indices whose non-empty data cells are all numeric. */
export function numericColumns(rows: readonly string[][]): Set<number> {
  const columns = new Set<number>();
  if (rows.length === 0) return columns;
  const width = rows.reduce((max, row) => Math.max(max, row.length), 0);
  for (let column = 0; column < width; column += 1) {
    const values = rows
      .map((row) => (row[column] ?? '').trim())
      .filter((value) => value !== '');
    if (values.length > 0 && values.every(isNumericCell)) columns.add(column);
  }
  return columns;
}
