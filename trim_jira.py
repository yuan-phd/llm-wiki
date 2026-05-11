"""
Trim Jira CSV to keep only useful columns.
Usage: python3 trim_jira.py <input_file> [output_file]
If output_file is not specified, overwrites input_file.
"""

import csv
import sys
import os

KEEP_COLUMNS = [
    'Summary',
    'Issue key',
    'Issue Type',
    'Status',
    'Assignee',
    'Reporter',
    'Created',
    'Updated',
    'Description',
    'Parent key',
    'Parent summary',
    'Custom field (Acceptance Criteria)',
    'Custom field (Hints)',
    'Custom field (Tracking)',
    'Custom field (Design)',
    'Custom field (Story point estimate)',
    'Comments',
]

def trim(input_file, output_file=None):
    if output_file is None:
        output_file = input_file

    with open(input_file, encoding='utf-8', newline='') as f:
        reader = list(csv.DictReader(f))

    if not reader:
        print('Error: CSV is empty')
        sys.exit(1)

    # Check which columns exist
    available = [c for c in KEEP_COLUMNS if c in reader[0]]
    missing = [c for c in KEEP_COLUMNS if c not in reader[0]]
    if missing:
        print(f'Warning: missing columns (skipped): {missing}')

    # Write trimmed file
    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=available)
        w.writeheader()
        for r in reader:
            w.writerow({k: r.get(k, '') for k in available})

    # Report
    total_chars = sum(len(str(r.get(k, ''))) for r in reader for k in available)
    tokens = total_chars // 4
    has_desc = sum(1 for r in reader if r.get('Description', '').strip())

    print(f'Input:  {input_file}')
    print(f'Output: {output_file}')
    print(f'Rows: {len(reader)}')
    print(f'Columns kept: {len(available)}/{len(KEEP_COLUMNS)}')
    print(f'Rows with Description: {has_desc}/{len(reader)} ({has_desc * 100 // len(reader)}%)')
    print(f'Est. tokens: {tokens:,}')
    print(f'Fits in one batch (< 25K): {tokens < 25000}')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 trim_jira.py <input.csv> [output.csv]')
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    trim(inp, out)
