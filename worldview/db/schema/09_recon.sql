-- WorldView :: 09_recon.sql
-- Layer C — Space. Predicted satellite recon windows (when a sensor footprint covers an
-- Area of Interest). The Python recon predictor materializes one row per (sat, AOI, pass);
-- the backend serves upcoming windows and emits due alerts (ticket H19.2.2).

-- ---------------------------------------------------------------------------
-- One predicted overflight of an AOI by a satellite's sensor footprint. The pass is
-- bracketed by ingress/peak/egress times; min_distance_km is the closest approach and
-- quality is the predictor's confidence/usefulness score. Idempotent on the PK so the
-- predictor can re-run (ON CONFLICT DO NOTHING) without duplicating windows.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recon_windows (
    norad_id        integer     NOT NULL,              -- satellite catalog number
    aoi_id          text        NOT NULL,              -- Area of Interest identifier
    sensor_type     text        NOT NULL,              -- optical | sar | sigint | other
    t_ingress       timestamptz NOT NULL,              -- footprint enters the AOI (time column)
    t_peak          timestamptz NOT NULL,              -- closest approach / best coverage
    t_egress        timestamptz NOT NULL,              -- footprint leaves the AOI
    min_distance_km double precision NOT NULL,         -- closest ground-track distance to AOI (km)
    sunlit_at_peak  boolean     NOT NULL,              -- target illuminated at peak (optical needs it)
    quality         double precision NOT NULL,         -- predictor confidence / usefulness score
    PRIMARY KEY (norad_id, aoi_id, t_ingress)
);

SELECT create_hypertable(
    'recon_windows', 't_ingress',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

-- AOI/time lookups ("upcoming windows for this AOI"): btree on (aoi_id, t_ingress).
CREATE INDEX IF NOT EXISTS recon_windows_aoi_idx
    ON recon_windows (aoi_id, t_ingress);
