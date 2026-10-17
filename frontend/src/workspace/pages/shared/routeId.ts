/* Route ids: a ":id" segment is a positive integer or the link is broken. */

/** The id in a route segment, or null when the segment is not a positive integer. */
export function routeId(value: string | undefined): number | null {
  const id = Number(value);
  return value !== undefined && Number.isInteger(id) && id > 0 ? id : null;
}

/** For a page whose drawer follows the URL: null when absent, -1 when the segment is broken. */
export function optionalRouteId(value: string | undefined): number | null {
  if (value === undefined) return null;
  return routeId(value) ?? -1;
}
