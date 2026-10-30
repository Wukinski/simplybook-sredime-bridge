"""Synthetic diagnostic checks for the resident model, without bridge state.

These cases check a small set of known decisions. Passing them is not a promise
that a model can discover every bug. The harness has no database, booking API,
repair operation, email sender or real customer data.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


ERROR_CODES = frozenset({'assessment_mismatch', 'model_response_invalid',
                         'model_unavailable', 'local_model_endpoint_required', 'model_check_failed'})


def _reference(label):
    return hashlib.sha256(('synthetic-watchdog-evaluation:' + label).encode()).hexdigest()[:16]


def _booking(label, *, start='10:00:00', end='11:00:00', status='confirmed'):
    return {'id_ref': _reference('booking-' + label), 'provider_ref': _reference('provider'),
            'service_ref': _reference('service'), 'start': '2030-01-15T' + start + '+00:00',
            'end': '2030-01-15T' + end + '+00:00', 'status': status, 'buffer_minutes': 0}


def _finding(case, code, severity='warning'):
    return {'code': code, 'severity': severity, 'reference': _reference(case + ':' + code)}


def _packet(bookings, *, findings=(), links=(), intents=0, events=0, issues=0, stale=False):
    return {'scan_complete': True,
            'counts': {'bookings': len(bookings), 'owned_links': len(links),
                       'events': events, 'intents': intents, 'issues': issues},
            'snapshot_statuses': {'bookings': 'stale' if stale else 'fresh',
                                  'buffers': 'stale' if stale else 'fresh', 'heartbeat': 'fresh'},
            'findings': deepcopy(list(findings)), 'bookings_sample': deepcopy(list(bookings)),
            'owned_links_sample': deepcopy(list(links)), 'sample_is_partial': False}


def synthetic_cases():
    """Return new, deterministic packets using only invented hashed identities."""
    first = _booking('first')
    adjacent = _booking('adjacent', start='11:00:00', end='12:00:00')
    overlapping = _booking('overlapping', start='10:30:00', end='11:30:00')
    duplicate = _booking('duplicate')
    canceled = _booking('canceled', status='canceled')
    cancel_link = {'source_ref': _reference('source-booking'), 'target_ref': first['id_ref'],
                   'state': 'canceled', 'source_state': 'canceled'}
    return deepcopy([
        {'name': 'healthy_adjacency', 'packet': _packet([first, adjacent]),
         'expected_assessment': 'no_additional_issue'},
        {'name': 'verified_overlap', 'packet': _packet([first, overlapping], findings=[
            _finding('verified_overlap', 'provider_overlap_confirmed', 'critical')]),
         'expected_assessment': 'operator_review'},
        {'name': 'duplicate_candidate', 'packet': _packet([first, duplicate], findings=[
            _finding('duplicate_candidate', 'duplicate_booking_candidate')]),
         'expected_assessment': 'operator_review'},
        {'name': 'source_canceled_target_active', 'packet': _packet([first], links=[cancel_link], findings=[
            _finding('source_canceled_target_active', 'owned_cancel_state_diverged', 'critical')]),
         'expected_assessment': 'operator_review'},
        {'name': 'unresolved_intent', 'packet': _packet([first], intents=1, events=1, findings=[
            _finding('unresolved_intent', 'unresolved_remote_intent', 'critical')]),
         'expected_assessment': 'operator_review'},
        {'name': 'stale_conflicting_data', 'packet': _packet([first, overlapping], stale=True, findings=[
            _finding('stale_conflicting_data', 'booking_snapshot_stale'),
            _finding('stale_conflicting_data', 'service_buffers_stale'),
            _finding('stale_conflicting_data', 'booking_evidence_insufficient'),
            _finding('stale_conflicting_data', 'provider_overlap_candidate')]),
         'expected_assessment': 'insufficient_evidence'},
        {'name': 'canceled_overlap_healthy', 'packet': _packet([first, canceled]),
         'expected_assessment': 'no_additional_issue'},
    ])


def run_model_checks(reviewer):
    """Run sequential inferences; retain only validated enums and fixed codes."""
    from .model import Review
    from .watchdog import validate_assessment

    tests = []
    for case in synthetic_cases():
        actual, error = None, None
        # A reviewer cannot alter the trusted packet used for output validation.
        packet = deepcopy(case['packet'])
        try:
            answer = reviewer.review(deepcopy(packet))
            result = validate_assessment(answer, packet)
            actual = result['assessment']
            if actual != case['expected_assessment']:
                error = 'assessment_mismatch'
        except Review as exc:
            error = str(exc) if str(exc) in ERROR_CODES else 'model_check_failed'
        except Exception:
            # Exceptions can contain model text, URLs, headers or other secrets.
            error = 'model_check_failed'
        tests.append({'name': case['name'], 'passed': error is None,
                      'expected': case['expected_assessment'], 'actual_assessment': actual,
                      'error_code': error})
    return {'schema_version': 1, 'synthetic_only': True, 'tests': tests,
            'passed': all(test['passed'] for test in tests)}


def _write_report(path, report):
    path = Path(path)
    if path.suffix.lower() != '.json':
        raise ValueError('synthetic_report_output_must_be_json')
    body = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.watchdog-eval-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    from .model import Review
    from .watchdog import OllamaReviewer

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-url', default='http://127.0.0.1:11434')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        reviewer = OllamaReviewer(args.model_url)
    except Review:
        # Keep the CLI result schema even if an endpoint is rejected before use.
        class RejectedEndpoint:
            def review(self, _packet):
                raise Review('local_model_endpoint_required')
        reviewer = RejectedEndpoint()
    report = run_model_checks(reviewer)
    output_ok = True
    if args.output is not None:
        try:
            _write_report(args.output, report)
        except (OSError, ValueError):
            output_ok = False
            print(json.dumps({'report_written': False, 'error_code': 'report_output_unavailable'}), file=sys.stderr)
    print(json.dumps(report, sort_keys=True))
    return 0 if report['passed'] and output_ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
