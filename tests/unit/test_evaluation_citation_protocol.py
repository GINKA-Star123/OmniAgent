from copy import deepcopy

import pytest

from aiagent.evaluation.contracts import Observation
from aiagent.evaluation.scoring import score
from aiagent.evaluation.semantic import Judge, Verdict
from aiagent.evaluation.source_attribution import is_evidence_citation_only
from tests.unit.test_evaluation_contracts import semantic_case
from tests.unit.test_evaluation_judge_protocol import provider, response, verdict


@pytest.mark.parametrize('quote', ['[doc]', '[doc]。', ' [doc] [other]；', '[doc],[other]'])
def test_only_known_structural_citation_tokens_are_identified(quote):
    assert is_evidence_citation_only(quote, {'doc': '星蓝', 'other': '资料'})


@pytest.mark.parametrize('quote', ['[unknown]', '[doc]是来源', '颜色是[doc]',
                                  '来源：《doc》', '[doc]2014年', '[doc][unknown]', '', '。'])
def test_unknown_labels_and_real_assertions_are_not_removed(quote):
    assert not is_evidence_citation_only(quote, {'doc': '星蓝'})


def cited_verdict():
    value = verdict()
    value['claims'][0]['citation_ids'] = ['doc']
    return value


def cited_observation():
    return Observation(scope='fixture', answer='星蓝。[doc]', evidence={'doc': '颜色是星蓝'})


def test_orphan_marker_is_protocol_error_not_silently_rescored(monkeypatch):
    raw = cited_verdict()
    raw['claims'].append({'quote': '[doc]', 'truth': 'unverifiable',
                          'support': 'insufficient', 'citation_ids': ['doc']})
    judge, calls = provider(monkeypatch, [response(raw)], max_repairs=0)
    result = score(semantic_case(), cited_observation(), judge, 'citation@1')
    assert result.status == 'judge_error'
    assert result.error_code == 'citation_marker_not_fact'
    assert len(calls) == 1
    assert 'fact_accuracy' not in result.metrics


def test_orphan_marker_can_receive_one_bounded_protocol_repair(monkeypatch):
    raw = cited_verdict()
    raw['claims'].append({'quote': '[doc]', 'truth': 'unverifiable', 'support': 'insufficient'})
    judge, calls = provider(monkeypatch, [response(raw), response(cited_verdict())], request_budget=2)
    result = score(semantic_case(), cited_observation(), judge, 'citation@1')
    assert result.status == 'passed'
    assert [d.code for d in result.judge_diagnostics] == ['citation_marker_not_fact', 'ok']
    assert result.metrics['claim_count'] == 1
    assert result.metrics['fact_accuracy'] == result.metrics['faithfulness'] == 1
    assert result.metrics['citation_accuracy'] == result.metrics['citation_coverage'] == 1
    assert len(calls) == 2


def test_known_citation_does_not_make_a_wrong_fact_correct(monkeypatch):
    raw = cited_verdict()
    raw['claims'][0].update(quote='暗红', truth='incorrect', support='contradicted', evidence_quotes={'doc': '星蓝'})
    raw.update(covered_gold_ids=[], coverage_claims={})
    case = semantic_case()
    case.oracle.limits['fact_accuracy'] = case.oracle.limits['gold_coverage']
    observation = cited_observation().model_copy(update={'answer': '暗红。[doc]'})
    judge, calls = provider(monkeypatch, [response(raw)])
    result = score(case, observation, judge, 'citation@1')
    assert result.status == 'failed'
    assert result.metrics['fact_accuracy'] == result.metrics['faithfulness'] == 0
    assert result.metrics['citation_accuracy'] == 0
    assert len(calls) == 1


def test_unknown_citation_is_still_inaccurate_without_dropping_fact():
    raw = cited_verdict()
    raw['claims'][0]['citation_ids'] = ['unknown']
    observation = cited_observation().model_copy(update={'answer': '星蓝。[unknown]'})
    payload = Judge().build_payload(semantic_case(), observation)
    value = Verdict.model_validate(raw)
    before = deepcopy(value.model_dump())
    metrics = Judge.score_verdict(value, payload)
    assert metrics['fact_accuracy'] == 1 and metrics['claim_count'] == 1
    assert metrics['citation_accuracy'] == 0
    assert value.model_dump() == before


def test_citation_protocol_version_is_explicit():
    assert Judge().identity['protocol'] == 'judge-v8'
