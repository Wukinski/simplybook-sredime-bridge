import copy
import json

import pytest

from booking_bridge import watchdog_eval as evaluation
from booking_bridge.model import Review
from booking_bridge.watchdog import ASSESSMENTS, SEVERITIES, known_references


class CorrectReviewer:
    def __init__(self):
        self.calls = []

    def review(self, packet):
        self.calls.append(copy.deepcopy(packet))
        case = evaluation.synthetic_cases()[len(self.calls) - 1]
        references = [packet['findings'][0]['reference']] if packet['findings'] else []
        return {'assessment': case['expected_assessment'], 'confidence': 'high',
                'finding_references': references, 'recommendation_codes': []}


def test_seven_synthetic_cases_have_the_exact_projected_packet_shape():
    cases = evaluation.synthetic_cases()
    assert len(cases) == len({case['name'] for case in cases}) == 7
    assert {case['expected_assessment'] for case in cases} == set(ASSESSMENTS)
    for case in cases:
        packet = case['packet']
        assert set(packet) == {'scan_complete', 'counts', 'snapshot_statuses', 'findings',
                               'bookings_sample', 'owned_links_sample', 'sample_is_partial'}
        assert all(row['severity'] in SEVERITIES for row in packet['findings'])
        assert all(len(ref) == 16 and all(char in '0123456789abcdef' for char in ref)
                   for ref in known_references(packet))
        assert set(packet['counts']) == {'bookings', 'owned_links', 'events', 'intents', 'issues'}
        assert packet['counts']['bookings'] == len(packet['bookings_sample'])
        assert packet['counts']['owned_links'] == len(packet['owned_links_sample'])


def test_fixtures_are_fresh_independent_objects_without_real_data():
    first = evaluation.synthetic_cases()
    first[0]['packet']['bookings_sample'][0]['status'] = 'canceled'
    first[0]['packet']['counts']['events'] = 999
    second = evaluation.synthetic_cases()
    assert second[0]['packet']['bookings_sample'][0]['status'] == 'confirmed'
    assert second[0]['packet']['counts']['events'] == 0
    assert first[1]['packet']['bookings_sample'][0]['status'] == 'confirmed'
    serialized = json.dumps(second)
    for forbidden in ('client_id', 'customer', 'email', 'phone', 'http://', 'https://', 'payload', 'notes'):
        assert forbidden not in serialized


def test_stale_overlap_has_only_qualified_findings_and_insufficient_expectation():
    case = next(case for case in evaluation.synthetic_cases() if case['name'] == 'stale_conflicting_data')
    assert case['expected_assessment'] == 'insufficient_evidence'
    assert case['packet']['snapshot_statuses']['bookings'] == 'stale'
    codes = {row['code'] for row in case['packet']['findings']}
    assert {'booking_evidence_insufficient', 'provider_overlap_candidate'} <= codes
    assert 'provider_overlap_confirmed' not in codes


def test_healthy_adjacency_and_canceled_overlap_have_no_issue_findings():
    cases = {case['name']: case for case in evaluation.synthetic_cases()}
    for name in ('healthy_adjacency', 'canceled_overlap_healthy'):
        assert cases[name]['packet']['findings'] == []
        assert cases[name]['expected_assessment'] == 'no_additional_issue'
    adjacent = cases['healthy_adjacency']['packet']['bookings_sample']
    assert adjacent[0]['end'] == adjacent[1]['start']
    canceled = cases['canceled_overlap_healthy']['packet']['bookings_sample']
    assert {row['status'] for row in canceled} == {'confirmed', 'canceled'}


def test_sequential_correct_reviewer_passes_all_checks():
    reviewer = CorrectReviewer()
    report = evaluation.run_model_checks(reviewer)
    assert report['schema_version'] == 1 and report['synthetic_only'] is True
    assert report['passed'] is True and len(reviewer.calls) == len(report['tests']) == 7
    assert all(row['passed'] and row['error_code'] is None and row['actual_assessment'] == row['expected']
               for row in report['tests'])
    for packet in reviewer.calls:
        assert packet in [case['packet'] for case in evaluation.synthetic_cases()]


def test_valid_but_wrong_assessment_is_a_failed_test():
    class AlwaysHealthy:
        def review(self, packet):
            return {'assessment': 'no_additional_issue', 'confidence': 'high',
                    'finding_references': [], 'recommendation_codes': []}
    report = evaluation.run_model_checks(AlwaysHealthy())
    assert report['passed'] is False
    assert sum(row['passed'] for row in report['tests']) == 2
    assert {row['error_code'] for row in report['tests'] if not row['passed']} == {'assessment_mismatch'}


@pytest.mark.parametrize('answer', [
    {'assessment': 'PRIVATE MODEL TEXT', 'confidence': 'high', 'finding_references': [], 'recommendation_codes': []},
    {'assessment': 'operator_review', 'confidence': 'high', 'finding_references': ['f' * 16], 'recommendation_codes': []},
    {'assessment': 'operator_review', 'confidence': 'high', 'finding_references': [], 'recommendation_codes': []},
    {'assessment': 'no_additional_issue', 'confidence': 'high', 'finding_references': [],
     'recommendation_codes': ['run PRIVATE SHELL COMMAND']},
])
def test_invalid_answers_or_unknown_references_are_rejected_without_echo(answer):
    class InvalidReviewer:
        def review(self, packet):
            return answer
    report = evaluation.run_model_checks(InvalidReviewer())
    assert not report['passed'] and all(row['error_code'] == 'model_response_invalid' for row in report['tests'])
    assert all(row['actual_assessment'] is None for row in report['tests'])
    assert 'PRIVATE' not in json.dumps(report)


@pytest.mark.parametrize('error,code', [
    (RuntimeError('PRIVATE TOKEN https://private.invalid'), 'model_check_failed'),
    (Review('PRIVATE MODEL RESPONSE'), 'model_check_failed'),
    (Review('model_unavailable'), 'model_unavailable'),
    (Review('model_response_invalid'), 'model_response_invalid'),
])
def test_errors_are_fixed_codes_and_do_not_abort_later_cases(error, code):
    class BrokenReviewer:
        calls = 0
        def review(self, packet):
            self.calls += 1
            raise error
    reviewer = BrokenReviewer()
    report = evaluation.run_model_checks(reviewer)
    assert not report['passed'] and reviewer.calls == 7
    assert all(row['error_code'] == code for row in report['tests'])
    assert 'PRIVATE' not in json.dumps(report) and 'private.invalid' not in json.dumps(report)


def test_reviewer_cannot_mutate_packet_to_authorize_an_invented_reference():
    class MutatingReviewer:
        def review(self, packet):
            packet['findings'].append({'reference': 'f' * 16})
            return {'assessment': 'operator_review', 'confidence': 'high',
                    'finding_references': ['f' * 16], 'recommendation_codes': []}
    report = evaluation.run_model_checks(MutatingReviewer())
    assert all(row['error_code'] == 'model_response_invalid' for row in report['tests'])


def test_cli_writes_only_synthetic_report_to_explicit_output(tmp_path, monkeypatch, capsys):
    import booking_bridge.watchdog as watchdog
    reviewer = CorrectReviewer()
    monkeypatch.setattr(watchdog, 'OllamaReviewer', lambda url: reviewer)
    output = tmp_path / 'checks' / 'synthetic.json'
    assert evaluation.main(['--output', str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_text(encoding='utf-8'))
    assert report['synthetic_only'] is report['passed'] is True
    assert not list(output.parent.glob('*.tmp'))


def test_cli_rejected_endpoint_has_sanitized_failure_schema(monkeypatch, capsys):
    import booking_bridge.watchdog as watchdog
    def rejected(_url):
        raise Review('local_model_endpoint_required')
    monkeypatch.setattr(watchdog, 'OllamaReviewer', rejected)
    assert evaluation.main(['--model-url', 'https://PRIVATE-REMOTE.invalid']) == 2
    report = json.loads(capsys.readouterr().out)
    assert not report['passed'] and report['synthetic_only'] is True
    assert all(row['error_code'] == 'local_model_endpoint_required' for row in report['tests'])
    assert 'PRIVATE' not in json.dumps(report)


def test_output_failure_preserves_model_result_schema_without_private_path(tmp_path, monkeypatch, capsys):
    import booking_bridge.watchdog as watchdog
    monkeypatch.setattr(watchdog, 'OllamaReviewer', lambda url: CorrectReviewer())
    assert evaluation.main(['--output', str(tmp_path / 'PRIVATE-PATH.invalid')]) == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report['passed'] is True and len(report['tests']) == 7
    assert json.loads(captured.err)['error_code'] == 'report_output_unavailable'
    assert 'PRIVATE' not in captured.err
