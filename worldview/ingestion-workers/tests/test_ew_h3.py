"""Tests for H3 jamming-grid aggregation."""

from worldview_ingest.ew.h3grid import aggregate_to_h3, cell_boundary_wkt


def test_aggregate_groups_nearby_points_into_one_cell():
    # Three observations within a few hundred meters land in the same r5 cell.
    obs = [
        (26.500, 56.200, 0.8),
        (26.501, 56.201, 0.6),
        (26.5005, 56.2005, 1.0),
    ]
    cells = aggregate_to_h3(obs, resolution=5)
    assert len(cells) == 1
    cell = cells[0]
    assert cell.sample_count == 3
    assert abs(cell.intensity - 0.8) < 1e-9  # mean of 0.8, 0.6, 1.0
    assert cell.boundary_wkt.startswith("POLYGON((")


def test_distant_points_separate_cells():
    cells = aggregate_to_h3([(26.5, 56.2, 0.5), (-33.9, 151.2, 0.9)], resolution=5)
    assert len(cells) == 2


def test_cell_boundary_is_closed_ring():
    wkt = cell_boundary_wkt("85283473fffffff")
    coords = wkt[len("POLYGON((") : -2].split(", ")
    assert coords[0] == coords[-1]
