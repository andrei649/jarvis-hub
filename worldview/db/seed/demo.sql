-- WorldView :: demo seed — a Strait of Hormuz scenario across all five layers.
-- Anchored to the last 10 minutes (relative to now()) with motion, so scrubbing the timeline
-- animates: a civil flight crossing east, a military orbit, a transiting tanker, a vessel that
-- goes dark mid-window, a SAR satellite pass, a GPS-jamming cell that ramps up, a NOTAM, and a
-- strike event. Apply after the schema:  psql "$DATABASE_URL" -f db/seed/demo.sql
--
-- View it: open the dashboard and scrub the timeline back ~10 minutes (historical mode).

BEGIN;

-- Clean prior demo data (CASCADE clears dark_vessel_events via the geofence FK).
TRUNCATE adsb_positions, ais_positions, satellite_ephemeris, gps_jamming,
         geopolitical_events, notams, dark_vessel_events, geofences CASCADE;

-- Watched choke point.
INSERT INTO geofences (name, category, dark_gap_seconds, geom) VALUES
 ('Strait of Hormuz', 'chokepoint', 1800,
  ST_SetSRID(ST_GeomFromText('MULTIPOLYGON(((55.6 25.8,57.2 25.8,57.2 27.0,55.6 27.0,55.6 25.8)))'), 4326));

-- Reference dimensions (persistent; upserted).
INSERT INTO aircraft (icao24, registration, type_code, operator, is_military) VALUES
 ('4ca7b3', 'A6-EOA', 'A388', 'Emirates', false),
 ('43c6db', 'ZZ-RCH', 'RC135', 'Reconnaissance', true)
ON CONFLICT (icao24) DO NOTHING;

INSERT INTO vessels (mmsi, name, vessel_type, flag) VALUES
 (636092297, 'EVER ELYSIUM', 'cargo', 'LR'),
 (412331100, 'DARK STAR', 'tanker', 'XX')
ON CONFLICT (mmsi) DO NOTHING;

INSERT INTO satellites (norad_id, name, operator, sensor_type) VALUES
 (40115, 'CAPELLA-10', 'Capella Space', 'sar')
ON CONFLICT (norad_id) DO NOTHING;
INSERT INTO sensors_footprint_params (norad_id, swath_width_km, swath_offset_km) VALUES
 (40115, 30, 20)
ON CONFLICT (norad_id) DO NOTHING;

-- Layer A — ADS-B: civil flight crossing east, climbing.
INSERT INTO adsb_positions (ts, icao24, geom, alt_m, gs_kt, track_deg, on_ground, is_military, source)
SELECT now() - interval '10 min' + make_interval(secs => i * 30),
       '4ca7b3',
       ST_SetSRID(ST_MakePoint(55.80 + i * 0.030, 26.30 + i * 0.004, 9000 + i * 40), 4326),
       9000 + i * 40, 450, 95, false, false, 'demo'
FROM generate_series(0, 20) AS i;

-- Layer A — ADS-B: military aircraft flying a holding orbit.
INSERT INTO adsb_positions (ts, icao24, geom, alt_m, gs_kt, track_deg, on_ground, is_military, source)
SELECT now() - interval '10 min' + make_interval(secs => i * 30),
       '43c6db',
       ST_SetSRID(ST_MakePoint(56.40 + 0.10 * cos(i * 0.5), 26.90 + 0.10 * sin(i * 0.5), 11000), 4326),
       11000, 420, (i * 30) % 360, false, true, 'demo'
FROM generate_series(0, 20) AS i;

-- Layer B — AIS: tanker transiting west-to-east.
INSERT INTO ais_positions (ts, mmsi, geom, sog_kt, cog_deg, heading_deg, nav_status, source)
SELECT now() - interval '10 min' + make_interval(secs => i * 30),
       636092297,
       ST_SetSRID(ST_MakePoint(56.80 - i * 0.012, 26.50 + i * 0.002), 4326),
       12, 290, 290, 0, 'demo'
FROM generate_series(0, 20) AS i;

-- Layer B — AIS: a vessel that stops transmitting after the halfway mark (goes dark).
INSERT INTO ais_positions (ts, mmsi, geom, sog_kt, cog_deg, heading_deg, nav_status, source)
SELECT now() - interval '10 min' + make_interval(secs => i * 30),
       412331100,
       ST_SetSRID(ST_MakePoint(56.30 + i * 0.010, 26.60 - i * 0.003), 4326),
       10, 110, 110, 0, 'demo'
FROM generate_series(0, 10) AS i;

-- Layer B — dark-vessel event flagged when the gap exceeds the threshold.
INSERT INTO dark_vessel_events (ts, mmsi, geofence_id, last_seen_ts, last_seen_geom, gap_seconds, extrapolated_geom, status)
SELECT now() - interval '4 min', 412331100, g.id, now() - interval '5 min',
       ST_SetSRID(ST_MakePoint(56.40, 26.57), 4326), 60,
       ST_SetSRID(ST_MakePoint(56.42, 26.56), 4326), 'dark'
FROM geofences g WHERE g.name = 'Strait of Hormuz';

-- Layer C — Space: a SAR satellite pass with a swept footprint (buffered ground circle).
INSERT INTO satellite_ephemeris (ts, norad_id, geom, velocity_kms, sensor_type, footprint)
SELECT now() - interval '10 min' + make_interval(secs => i * 30),
       40115,
       ST_SetSRID(ST_MakePoint(54.0 + i * 0.25, 24.0 + i * 0.18, 500000), 4326),
       7.5, 'sar',
       ST_Buffer(ST_SetSRID(ST_MakePoint(54.2 + i * 0.25, 24.0 + i * 0.18), 4326), 0.3)
FROM generate_series(0, 20) AS i;

-- Layer D — EW: a GPS-jamming H3 cell that ramps up in the second half of the window.
INSERT INTO gps_jamming (ts, h3_index, h3_resolution, h3_geom, intensity, sample_count, source)
SELECT now() - interval '10 min' + make_interval(secs => i * 30),
       '85283473fffffff', 5,
       ST_SetSRID(ST_GeomFromText(
         'POLYGON((56.50 26.60,56.62 26.60,56.68 26.68,56.62 26.76,56.50 26.76,56.44 26.68,56.50 26.60))'), 4326),
       least(1.0, (i - 8) * 0.12), 10, 'demo'
FROM generate_series(8, 20) AS i;

-- Layer E — NOTAM: airspace closure active across the window.
INSERT INTO notams (id, notam_type, effective_from, effective_to, geom, source) VALUES
 ('A1234/26', 'airspace_closure', now() - interval '1 hour', now() + interval '6 hours',
  ST_SetSRID(ST_GeomFromText('POLYGON((56.2 26.7,56.9 26.7,56.9 27.1,56.2 27.1,56.2 26.7))'), 4326), 'demo');

-- Layer E — geopolitical event.
INSERT INTO geopolitical_events (ts, event_id, category, severity, geom, source, metadata) VALUES
 (now() - interval '6 min', 'evt-demo-1', 'strike', 4,
  ST_SetSRID(ST_MakePoint(56.55, 26.62), 4326), 'demo', '{"note":"demo strike"}'::jsonb);

COMMIT;
