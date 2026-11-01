"""A page's text or element tree is cut to the browser_run budget, not refused (#1321).

The driver keeps 20,000 characters of page text and up to 500 snapshot elements, while the
whole trace must stay inside the 20,000 bytes browser_run declares. An ``extract`` of an
ordinary page, or a ``snapshot`` of a page with a hundred links, refused with
``browser_output_too_large`` and the start step tore its new session down.
"""
from __future__ import annotations

import json

import pytest

from agents.core.browser_runtime import (
    _TRACE_BYTES,
    BrowserPlanRefused,
    _append_within_budget,
    _trace_bytes,
)


def _navigate() -> dict:
    return {'action': 'navigate', 'status': 'done',
            'result': {'url': 'https://example.test/', 'title': 'Example'}}


def test_an_extract_of_a_long_page_is_cut_to_the_budget_and_marked():
    text = ('Știință și tehnică — ' * 1200)[:20_000]           # two bytes per diacritic
    trace = [_navigate()]
    _append_within_budget(trace, {'action': 'extract', 'status': 'done',
                                  'result': {'text': text, 'truncated': False,
                                             'url': 'https://example.test/'}})
    kept = trace[-1]['result']
    assert _trace_bytes(trace) <= _TRACE_BYTES
    assert kept['truncated'] is True and text.startswith(kept['text'])
    assert len(kept['text']) > 5_000                            # cut to fit, not emptied
    # One more character would not have fit.
    kept['text'] = text[:len(kept['text']) + 1]
    assert _trace_bytes(trace) > _TRACE_BYTES


def test_a_snapshot_keeps_every_ref_and_cuts_only_the_element_tree():
    elements = [{'ref': f'aria-{i}', 'role': 'link', 'name': f'Item number {i}', 'depth': 2,
                 'rect': {'x': 0, 'y': i * 20, 'width': 300, 'height': 18}, 'attrs': {}}
                for i in range(361)]
    refs = [{'ref': f'@e{i}', 'role': 'link', 'name': f'Item number {i}'} for i in range(60)]
    result = {'observation': 'structured_ui', 'elements': elements, 'count': len(elements),
              'truncated': False, 'chars': 10_227, 'url': 'https://example.test/',
              'refs': refs, 'generation': 1}
    assert len(json.dumps(result).encode()) > _TRACE_BYTES
    trace = [_navigate()]
    _append_within_budget(trace, {'action': 'snapshot', 'status': 'done', 'result': result})
    assert _trace_bytes(trace) <= _TRACE_BYTES
    assert result['refs'] == refs                               # the act step needs them all
    assert result['truncated'] is True
    assert 0 < result['count'] == len(result['elements']) < len(elements)
    assert result['elements'] == elements[:result['count']]


def test_a_small_output_is_untouched():
    trace = []
    outcome = {'action': 'extract', 'status': 'done',
               'result': {'text': 'short', 'truncated': False, 'url': 'https://example.test/'}}
    _append_within_budget(trace, outcome)
    assert trace == [outcome] and outcome['result']['truncated'] is False


@pytest.mark.parametrize('outcome', [
    {'action': 'console', 'status': 'done', 'result': [{'text': 'x' * 25_000}]},
    {'action': 'snapshot', 'status': 'done',
     'result': {'elements': [], 'refs': [{'ref': '@e1', 'name': 'x' * 25_000}]}},
])
def test_an_output_that_cannot_be_cut_still_refuses(outcome):
    with pytest.raises(BrowserPlanRefused, match='browser_output_too_large'):
        _append_within_budget([_navigate()], outcome)
