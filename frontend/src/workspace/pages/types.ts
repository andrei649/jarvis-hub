/* The contract between the router and a page: the route's decoded ":name" parameters. */
import type { Params } from '../router';

export interface PageProps {
  params: Params;
}
