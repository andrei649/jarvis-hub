import pg from "pg";
import { config } from "../config.js";

// TimescaleDB + PostGIS pool (design doc §5/§8). STEP 4 runs the as-of-T reconstruction
// queries (DISTINCT ON ... WHERE ts <= T) through this pool.
let pool: pg.Pool | null = null;

export function getPool(): pg.Pool {
  if (!pool) {
    pool = new pg.Pool({ connectionString: config.databaseUrl });
  }
  return pool;
}
