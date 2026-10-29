"""Owner CLI speaks only the governed API and never prints stdin secrets."""
import io
import json

from agents.cli.nerva import Context, main


class FakeHub:
    def __init__(self):
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return {'identity': 'custom:office', 'configured': bool(body and body.get('secret')),
                'generation': 1, 'secret': 'synthetic-private-value'}


def _run(args, *, secret=''):
    hub = FakeHub()
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO(secret),
                  client_factory=lambda _env: hub)
    code = main(['provider', 'custom', *args], context=ctx)
    return code, hub.calls, out.getvalue(), err.getvalue()


def test_named_custom_cli_uses_guarded_routes_and_explicit_acknowledgments():
    code, calls, output, _ = _run(['create', '--key', 'office', '--name', 'Office',
                                  '--base-url', 'https://example.org/v1', '--model', 'm',
                                  '--auth-type', 'bearer', '--data-policy', 'unknown',
                                  '--grant-destination'])
    assert code == 0
    assert calls[0] == ('POST', '/api/admin/llm/custom-endpoints', {
        'key': 'office', 'name': 'Office', 'base_url': 'https://example.org/v1',
        'model': 'm', 'auth_type': 'bearer', 'data_policy': 'unknown',
        'grant_destination': True})
    assert json.loads(output)['identity'] == 'custom:office'
    assert 'synthetic-private-value' not in output
    code, calls, _, _ = _run(['activate', 'office', '--revision', '2',
                              '--choice-epoch', '7', '--acknowledge-unknown-price',
                              '--acknowledge-data-policy', '--grant-destination'])
    assert code == 0
    assert calls[0][2] == {'expected_revision': 2, 'expected_choice_epoch': 7,
                           'acknowledge_unknown_price': True,
                           'acknowledge_data_policy': True, 'grant_destination': True}


def test_cli_credential_stdin_is_not_echoed_and_missing_secret_refuses():
    secret = 'synthetic-very-private-value'
    code, calls, output, err = _run(['credential-set', 'office'], secret=secret + '\n')
    assert code == 0
    assert calls == [('PUT', '/api/admin/llm/custom-endpoints/office/credential',
                      {'secret': secret})]
    assert secret not in output + err
    code, calls, output, err = _run(['credential-set', 'office'])
    assert code == 2 and calls == []
    assert secret not in output + err
