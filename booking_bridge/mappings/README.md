# Explicit source identity mappings

Runtime mapping keys are the exact SrediMe IDs from a verified webhook. They are
case sensitive strings. Native UI employee/service/client numbers belong to a
different namespace. Do not decode opaque IDs, infer identity from a name or
contact, or treat `external_id` as permission to create a mapping.

The completed booking `9VPLV6E` has a private, booking-specific identity binding.
That evidence does not establish a reusable resolver or approve mappings for
other bookings, employees, services or clients. The new format below prepares
future reviewed configurations; it does not apply the historical binding.

## CSV configuration

New catalogs separate these columns:

| Column | Meaning |
|---|---|
| `sredime_webhook_id` | Exact authoritative source key used by the runtime |
| `sredime_native_id` | Optional positive decimal string, retained as `native_id` metadata only |
| `sredime_id` | Deprecated legacy key; leave blank in new catalogs |
| `simplybook_id` | Explicit target ID |
| `external_id` | Optional cross-check against the webhook field, never an identity resolver |

For example, using invented identifiers:

```csv
sredime_webhook_id,sredime_native_id,sredime_id,simplybook_id,external_id
Synthetic-Opaque-A,12345,,81,81
```

The runtime loads `employees.local.csv` and `services.local.csv`. A row without a
webhook key stays unmapped even when it has a native UI number. If the explicit
webhook column is present, a nonblank legacy key must exactly match it; a native
legacy value cannot silently take its place. Old CSV files that only contain
`sredime_id` continue to use that column as their source key. Such legacy files
are supported for compatibility, not evidence that their keys are webhook IDs.

Duplicate source keys, duplicate employee targets, malformed native metadata and
conflicting CSV/JSON mapping sources stop configuration loading. Source strings
are neither case-normalized nor decoded. Native metadata cannot route an event.

`python -m booking_bridge.prepare_mappings` regenerates the public catalogs from
existing import/account evidence without API calls. Both identifier columns
start blank. It does not edit `.local.csv` or approve any mapping.

## JSON configuration

An isolated JSON profile uses the exact webhook strings as dictionary keys:

```json
{
  "allowed_employees": ["Synthetic-Opaque-A"],
  "employees": {
    "Synthetic-Opaque-A": {"id": 81, "native_id": "12345", "external_id": "81"}
  },
  "services": {
    "Synthetic-Opaque-Service": {
      "id": 91,
      "native_id": "23456",
      "duration": 30,
      "timing_verified": true,
      "resources_verified": true
    }
  },
  "clients": {"Synthetic-Opaque-Client": 71}
}
```

Use the same employee webhook key for `allowed_employees`,
`schedule_service_ids`, private feed tokens and export URL dictionaries. Native
UI values stay in metadata or the private identity review; never add them as
fallback keys or automatically rewrite a stored signed event. Client mappings
remain explicit webhook-key-to-target-ID entries; their native UI provenance
stays in the private review.

This illustrative fragment does not supply pilot approvals, credentials or
validated business identity. Prepare a separate reviewed profile and retain the
original signed-event hash and identity evidence before any future activation.
