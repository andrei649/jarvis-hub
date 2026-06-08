# WorldView — tiered storage (ticket H19.1.7)

The explicit **HOT → WARM → COLD** storage lifecycle for the OSINT hypertables.
The SQL lives in [`db/schema/14_tiering.sql`](../../db/schema/14_tiering.sql) and
**extends** the compression + retention + continuous-aggregate policies already
in [`db/schema/07_policies.sql`](../../db/schema/07_policies.sql). There is no
compose stack to run here — tiering is policy DDL applied to TimescaleDB plus the
existing [`lakehouse/`](../lakehouse/) lake as the cold destination.

```
 writes ─► HOT  (uncompressed row-store chunks, TimescaleDB)
              │  add_compression_policy(<age>)         HOT → WARM
              ▼
           WARM (compressed columnstore chunks, TimescaleDB, ~10-20x smaller, queryable)
              │  add_retention_policy(<age>)  drops the OLTP chunk; releases storage
              ▼
           COLD (Parquet in s3://worldview-lake — already streamed from Kafka,
                 queryable with DuckDB; deploy/lakehouse/)
```

The lake is **not** filled by retention — every raw envelope is captured to
Parquet from the `osint.*` topics *as it streams* (independent of the OLTP
writers). So when retention drops a raw chunk, the full-fidelity record is
**already** in COLD. Retention only releases TimescaleDB storage. In parallel,
the **continuous aggregates** (`adsb_positions_1m`, `ais_positions_1m`) are
separate hypertables that **survive retention**, so long-range zoomed-out
scrubbing keeps working in-DB even after the raw chunks are gone.

## Per-layer tiers (the tuned ages)

| Hypertable | Chunk | Velocity | Columnstore (segmentby) | HOT→WARM (compress) | WARM→drop (retention) | Cold copy |
| --- | --- | --- | --- | --- | --- | --- |
| `adsb_positions` | 1h | highest | yes (`icao24`) | 2 days | **90 days** | lake `osint.adsb` |
| `ais_positions` | 6h | high | yes (`mmsi`) | 2 days | **180 days** | lake `osint.ais` |
| `satellite_ephemeris` | 1d | medium | yes (`norad_id`) | 7 days | **180 days** | lake `osint.tle` |
| `gps_jamming` | 1d | medium | yes (`h3_index`) | 7 days | **365 days** | lake `osint.ew` |
| `internet_outages` | 1d | low | no | — | **365 days** | lake `osint.ew` |
| `recon_windows` | 1d | low (intel) | yes (`aoi_id`) † | 30 days | **730 days** | lake `osint.recon` |
| `dark_vessel_events` | 7d | low (intel) | yes (`mmsi`) † | 30 days | **none** (kept) | lake `osint.ais` |
| `geopolitical_events` | 7d | low (intel) | yes (`category`) † | 30 days | **none** (kept) | lake `osint.context` |
| `adsb_positions_1m` / `ais_positions_1m` | rollup | — | — | — | none (survive) | — |

† Columnstore for the three intel layers is **added by 14_tiering.sql** (07 does
not touch them). They keep **no retention**, so compressing their old chunks
shrinks the permanently-resident footprint while staying queryable.

`tle_catalog` is a plain table (not a hypertable): it is the raw audit trail for
re-deriving `satellite_ephemeris`, so it carries no chunk retention.

Where 14's ages equal 07's, the `add_*_policy(... if_not_exists => TRUE)` calls
are idempotent no-ops; `recon_windows` retention and the three intel-layer
columnstores are the genuinely new bits. **14 contains no `ALTER ... ADD COLUMN`
on a compressed hypertable** (the columnstore restriction that broke CI once) —
only policy DDL and pre-policy `SET (compress …)` options.

## Storage-size math (rough, per layer)

The HOT footprint is what the OLTP store must keep on fast disk; WARM is HOT ÷
compression-ratio; COLD is unbounded but cheap (object storage). Plug your own
row-rate `R` (rows/s) and per-row bytes `B`:

```
HOT bytes   ≈ R × B × (compress_age in seconds)
WARM bytes  ≈ R × B × (retention_age − compress_age) ÷ CR        (CR ≈ 10–20x)
OLTP total  ≈ HOT + WARM                       (everything past retention → COLD only)
```

Worked example — `adsb_positions` at a sustained 5,000 msg/s, ~120 B/row, CR≈12:

```
HOT  (0–2d uncompressed):  5000 × 120 × 172,800 s   ≈ 104 GB
WARM (2–90d compressed):   5000 × 120 × 7,603,200 s / 12 ≈ 380 GB
OLTP total (adsb)          ≈ 0.48 TB resident; everything >90d lives only in COLD.
```

Lower-velocity layers are far smaller; the intel layers (no retention) are
dominated by their compressed WARM footprint, which is why 14 enables their
columnstore. Tune `compress_age` down to shrink HOT, `retention_age` down to
shrink WARM/OLTP — COLD (the lake) absorbs whatever ages out.

## Inspecting / retuning

Read-only inspection queries (policy jobs, compression ratios, per-chunk tier)
are in the `OPERATIONS` block at the bottom of
[`14_tiering.sql`](../../db/schema/14_tiering.sql). To change an age, the policy
must be removed then re-added (the `add_*` calls are no-ops while one exists):

```sql
SELECT remove_compression_policy('adsb_positions');
SELECT add_compression_policy('adsb_positions', INTERVAL '1 day', if_not_exists => TRUE);
```

## Enterprise tiered storage (not in this OSS image)

`timescale/timescaledb-ha:pg16` has **no** managed object-tiering. On
TimescaleDB Cloud / Enterprise, `add_tiering_policy(<table>, <age>)` would MOVE
aged chunks to a managed S3 tier that stays transparently queryable through the
same SQL — slotting in *instead of* `add_retention_policy` (drop). The
documentation block at the bottom of `14_tiering.sql` shows the exact swap; the
per-layer ages above are the thresholds to reuse. The lake stays useful either
way as the engine-agnostic raw archive.
