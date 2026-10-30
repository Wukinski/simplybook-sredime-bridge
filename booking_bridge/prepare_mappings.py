"""Read existing evidence, never import services or call an API."""
import csv
import json

from .model import HOME, ROOT


def main():
    folder = HOME / 'mappings'
    folder.mkdir(parents=True, exist_ok=True)
    checkpoint = json.loads((ROOT / 'service_importer/progress_log.json').read_text(encoding='utf-8'))
    with (folder / 'services.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['sredime_webhook_id', 'sredime_native_id', 'sredime_id',
                                 'external_id', 'simplybook_id', 'name',
                                 'duration_minutes', 'excel_row', 'timing_verified', 'resources_verified'])
        writer.writeheader()
        for key, row in sorted(checkpoint['rows'].items(), key=lambda pair: int(pair[0])):
            if row['status'] != 'confirmed':
                raise ValueError('Unconfirmed imported row')
            writer.writerow({'simplybook_id': row['remote_id'], 'name': row['normalized']['name'],
                             'duration_minutes': row['normalized']['duration_minutes'], 'excel_row': key,
                             'timing_verified': 'no', 'resources_verified': 'no'})
    audit = json.loads((HOME / 'evidence/account-read-check.json').read_text(encoding='utf-8'))
    with (folder / 'employees.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['sredime_webhook_id', 'sredime_native_id', 'sredime_id',
                                                   'external_id', 'simplybook_id', 'name'])
        writer.writeheader()
        for provider in audit['providers']:
            writer.writerow({'simplybook_id': provider['id'], 'name': provider['name']})
    print('Prepared explicit mapping catalogs. Webhook and native UI IDs are separate and intentionally blank; no mappings applied.')


if __name__ == '__main__':
    main()
