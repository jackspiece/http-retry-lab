"""Run real loopback HTTP failures and publish their observed outcomes."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import html
import http.client
import json
from pathlib import Path
import platform

from local_service import LocalService
from retry_client import Outcome, post_once, submit

ROOT = Path(__file__).resolve().parent
SOURCE = 'https://github.com/jackspiece/http-retry-lab'
PAYLOAD = {'request_id': 'example-001', 'subject': 'Move the workshop booking'}


def naive_retry(service):
    events = []
    for attempt in (1, 2):
        try:
            status, body = post_once(service.url, PAYLOAD)
            receipt = json.loads(body)
            events.append({'attempt': attempt, 'event': 'receipt_received', 'http_status': status})
            return Outcome('complete', attempt, receipt['ticket_id'], events)
        except (OSError, http.client.HTTPException) as error:
            events.append({'attempt': attempt, 'event': 'outcome_uncertain', 'error_type': type(error).__name__})
    raise RuntimeError('The baseline fixture did not produce its expected second response')


def experiments():
    definitions = [
        ('blind', 'Blind retry', False, False, 'drop_after_write', 'complete', 2, 2,
         'The first write succeeded. Repeating the POST created a second ticket.'),
        ('key', 'Same key, provider support', True, True, 'drop_after_write', 'complete', 2, 1,
         'The second request recovered the receipt for the original ticket.'),
        ('review', 'Stop for review', False, False, 'drop_after_write', 'review_required', 1, 1,
         'The client has no receipt. It stops instead of guessing whether another write is safe.'),
        ('ignored', 'Provider ignores the key', False, True, 'drop_after_write', 'complete', 2, 2,
         'Sending the header did not create an idempotency contract. The client assumption was wrong.'),
        ('rejected', 'Validation rejection', True, True, 'reject', 'rejected', 1, 0,
         'The fixture rejected the request before writing. The client did not retry.'),
    ]
    results = []
    for code, title, supports, declared, fault, expected_state, attempts, records, explanation in definitions:
        with LocalService(supports_keys=supports, faults=(fault,)) as service:
            if code == 'blind':
                outcome = naive_retry(service)
            else:
                outcome = submit(service.url, PAYLOAD, provider_supports_keys=declared,
                                 key='same-operation' if declared else None)
            observed = service.snapshot()
            actual = (outcome.state, len(observed['requests']), len(observed['records']))
            expected = (expected_state, attempts, records)
            if actual != expected:
                raise AssertionError(f'{code}: observed {actual}, expected {expected}')
            results.append({'id': code, 'title': title, 'explanation': explanation,
                            'provider_supports_keys': supports, 'client_declares_support': declared,
                            'outcome': asdict(outcome), 'observed': observed})
    return results


def render(report):
    cases = report['cases']
    cards = []
    for case, color in zip(cases[:3], ('red', 'green', 'amber')):
        count = len(case['observed']['records'])
        cards.append(f'<article class="card {color}"><h2>{html.escape(case["title"])}</h2>'
                     f'<div class="number">{count}<span> ticket{"s" if count != 1 else ""}</span></div>'
                     f'<p>{html.escape(case["explanation"])}</p></article>')
    rows = []
    traces = []
    for case in cases:
        state = case['outcome']['state'].replace('_', ' ')
        rows.append(f'<tr><th scope="row">{html.escape(case["title"])}</th>'
                    f'<td>{len(case["observed"]["requests"])}</td><td>{len(case["observed"]["records"])}</td>'
                    f'<td>{html.escape(state)}</td></tr>')
        trace = json.dumps({'client': case['outcome'], 'server': case['observed']}, indent=2)
        traces.append(f'<details><summary>{html.escape(case["title"])}</summary>'
                      f'<pre>{html.escape(trace)}</pre></details>')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="A reproducible Python experiment showing duplicate writes after a lost HTTP response, keyed recovery, and an explicit review state.">
<title>Where duplicate writes begin | jackspiece</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f3ed;color:#172d32;font:17px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
a{{color:#075d78;text-underline-offset:4px}}a:hover{{color:#003b4d}}.wrap{{max-width:1120px;margin:auto;padding:30px 28px 60px}}
nav{{display:flex;justify-content:space-between;gap:20px;padding-bottom:24px;border-bottom:1px solid #cad3cc;font-size:14px}}
nav a{{font-weight:650}}.eyebrow{{font:700 12px/1.4 ui-monospace,monospace;letter-spacing:.14em;color:#526963;text-transform:uppercase;margin-top:52px}}
h1{{font-size:clamp(36px,5.5vw,64px);line-height:1.06;letter-spacing:-.04em;max-width:800px;margin:16px 0 22px}}
.intro{{font-size:20px;max-width:760px;margin-bottom:35px}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.card{{padding:25px;border:1px solid #cad3cc;border-top:5px solid #78998e;border-radius:5px;background:#fffefa}}
.card h2{{font-size:16px;margin:0;line-height:1.4;min-height:44px}}.number{{font-size:58px;font-weight:720;line-height:1.2;margin:18px 0}}
.number span{{font-size:19px;font-weight:500;white-space:nowrap}}.card p{{font-size:15px;margin:10px 0 0}}
.red{{border-top-color:#b15339}}.green{{border-top-color:#32806b}}.amber{{border-top-color:#b38b29}}
.note{{font-size:14px;color:#50665f;margin:20px 0 42px;max-width:830px}}section{{margin-top:38px}}h2{{font-size:25px;letter-spacing:-.02em;margin:0 0 16px}}
.table-wrap{{overflow:auto;border:1px solid #cad3cc;border-radius:5px}}table{{border-collapse:collapse;width:100%;background:#fffefa;font-size:15px}}
th,td{{padding:15px 18px;border-bottom:1px solid #dfe5df;text-align:left}}thead{{background:#e6ece5}}tbody th{{font-weight:550;min-width:210px}}tr:last-child th,tr:last-child td{{border-bottom:0}}
.explain{{display:grid;grid-template-columns:1fr 1fr;gap:35px;margin:40px 0}}.explain p{{margin:0;font-size:16px}}
details{{background:#fffefa;border:1px solid #cad3cc;border-radius:5px;margin:10px 0}}summary{{cursor:pointer;padding:16px 18px;font-size:15px;font-weight:650}}
summary:focus-visible,a:focus-visible{{outline:3px solid #227d97;outline-offset:3px}}pre{{margin:0;padding:18px;overflow:auto;background:#edf1eb;font:13px/1.6 ui-monospace,monospace}}
.run{{padding:20px 24px;background:#172d32;color:#e6eee9;border-radius:5px;overflow:auto;font:14px/1.9 ui-monospace,monospace;white-space:pre}}
footer{{margin-top:45px;border-top:1px solid #cad3cc;padding-top:20px;font-size:13px;color:#50665f}}.links{{display:flex;flex-wrap:wrap;gap:18px;margin-top:22px}}
@media(max-width:740px){{.wrap{{padding:22px 18px 40px}}.eyebrow{{margin-top:32px}}.intro{{font-size:18px}}.cards,.explain{{grid-template-columns:1fr}}.card h2{{min-height:0}}.number{{margin:12px 0}}.card{{padding:21px}}.explain{{gap:24px}}table{{table-layout:fixed;font-size:12px;line-height:1.45}}th,td{{padding:11px 7px;overflow-wrap:anywhere}}thead th:first-child{{width:37%}}tbody th{{min-width:0}}nav{{font-size:13px}}}}
</style></head><body><main class="wrap">
<nav><span>jackspiece / small systems, checked</span><a href="{SOURCE}">Source &amp; tests</a></nav>
<p class="eyebrow">HTTP · failure handling · Python</p>
<h1>Where duplicate writes begin.</h1>
<p class="intro">A server saves the ticket. The connection closes before its reply arrives. This local experiment measures what happens next under three different retry policies.</p>
<div class="cards">{''.join(cards)}</div>
<p class="note">These counts come from the local server's records. In the review case, the client cannot see that a ticket exists. A missing response does not establish whether the write happened.</p>
<section><h2>The observed results</h2><div class="table-wrap"><table>
<thead><tr><th>Scenario</th><th>Requests</th><th>Tickets saved</th><th>Client state</th></tr></thead><tbody>{''.join(rows)}</tbody>
</table></div></section>
<div class="explain"><section><h2>The key is a contract.</h2><p>Reusing an operation key works here because the server remembers the original request and returns its receipt. The fourth case sends the same header to a server that ignores it. Two tickets are still created.</p></section>
<section><h2>Review is a useful outcome.</h2><p>When the client cannot establish that a retry is safe, it records an uncertain result. A real workflow can reconcile that operation before deciding to send another write.</p></section></div>
<section><h2>Inspect the request traces</h2>{''.join(traces)}</section>
<section><h2>Run it yourself</h2><div class="run">python -m unittest -v
python run_demo.py</div><p class="note">Python's standard library. Real HTTP on 127.0.0.1. Fictional tickets. The fixture's records and key cache live in memory for each case; this experiment measures response loss, not recovery from a database or machine crash.</p></section>
<div class="links"><a href="run.json" download>Download the measured run</a><a href="{SOURCE}/blob/main/README.md">Read the assumptions</a><a href="https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2">HTTP retry semantics</a></div>
<footer>Recorded {html.escape(report['generated_at'])} · Python {html.escape(report['python'])} · {html.escape(report['os'])}. Source hashes are included in the run file.</footer>
</main></body></html>'''


def main():
    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'python': platform.python_version(), 'os': platform.system(),
              'transport': 'real loopback HTTP; TCP response deliberately closed after write',
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                for name in ('retry_client.py', 'local_service.py', 'test_retry_lab.py', 'run_demo.py')},
              'cases': experiments()}
    out = ROOT / 'docs'
    out.mkdir(exist_ok=True)
    (out / '.nojekyll').write_text('', encoding='utf-8')
    (out / 'run.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (out / 'index.html').write_text(render(report), encoding='utf-8')
    print(json.dumps({'generated_at': report['generated_at'], 'cases': [
        {'case': c['id'], 'requests': len(c['observed']['requests']),
         'records': len(c['observed']['records']), 'client': c['outcome']['state']}
        for c in report['cases']]}, indent=2))


if __name__ == '__main__':
    main()
