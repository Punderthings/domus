# Sample Home dataset

A small, fictional example property for demos, tests, and trying out Domus. All names, model numbers, serials, MAC addresses, and Home Assistant ids are made up. The MAC addresses use the locally administered `02:00:5e` prefix so they can't collide with real hardware.

## What's in it

- **Property**: "Sample Home", with one building, **House**.
- **Floors**: Main Floor and Basement.
- **Rooms**: Kitchen, Living Room, Primary Bedroom, and Utility Room.
- **Devices** (9):

  | Device | Room | Shows off |
  | :-- | :-- | :-- |
  | Refrigerator | Kitchen | A manual link, a serial, a warranty, and a filter task every 6 months counted from the last change |
  | Kitchen Smoke Detector | Kitchen | A yearly fixed-date task (November 1), already overdue in the demo |
  | Living Room Light Switch | Living Room | Home Assistant device and entity ids, a MAC address, and a location on the wall ("right of the front door, 3-gang box") |
  | Wi-Fi Access Point | Living Room | A network device that other devices are `networked_via` |
  | Game Console | Living Room | A device a Maintainer added, on the Wi-Fi network |
  | Primary Bedroom Ceiling Light | Primary Bedroom | Access rules: guests and Maintainers can see it but not control it |
  | Gas Furnace | Utility Room | A **critical** item that only Admins can change, with a filter task every 3 months |
  | Sump Pump with Battery Backup | Utility Room | A yearly battery test in April |
  | Outdoor Hose Bib Shutoff Valve | Utility Room | The November "close the valve and drain the hose" task, with a written procedure |

- **Also included**: 5 maintenance tasks, 2 past maintenance events with costs, 2 tags (`smart`, `winterize`), and 4 access rules.

## Format

The layout is an unzipped `.hiotbak` partial export, as described in [data-storage-backup.md](../../docs/_prompts/plan/data-storage-backup.md) section 4:

```
manifest.json          format version, kind "partial", row counts
data/<table>.jsonl     one JSON object per row, column names from the data model
```

- **No files:** there are no blobs, so manuals are external links and there are no photos.
- **Fixed ids:** every id is a fixed UUIDv7, so tests can refer to specific records.
- **Schema version:** `app_version` and `schema_version` are null until the first database migration exists.

## Importing

Import it into a new or existing database (the command migrates the database first):

```sh
domus restore examples/sample-home --merge --dry-run   # preview
domus restore examples/sample-home --merge             # import
```

The import upserts by id, so running it again changes nothing. A test imports this dataset into a fresh database on every CI run and checks the row counts against `manifest.json`.

When the data model changes, update this dataset in the same PR so it stays importable.
