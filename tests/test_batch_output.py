import json
from app.evaluation.batch import BatchRecord, RunRecord
from app.evaluation.batch_output import write_batch_summary


def test_artifacts_preserve_missing_slots_and_primary_order(tmp_path):
    batch = BatchRecord("b", "now", {}, [RunRecord("1", "s", 1, {})])
    j, m = write_batch_summary(batch, tmp_path)
    doc = json.loads(j.read_text())
    assert doc["runs"][0]["trajectory"] is None
    text = m.read_text()
    assert text.index("Scenario checks passed") < text.index("Tool failure rate")
    assert "p95" not in text


def test_errors_redacted_and_relative_links(tmp_path):
    trajectory = tmp_path / 'trace.json'
    trajectory.write_text('{}')
    r = RunRecord('1','s',1,{},report={'error':'C:/Users/Secret/password', 'metrics':{}},trajectory_path=trajectory)
    paths = write_batch_summary(BatchRecord('b','now',{},[r]),tmp_path/'reports')
    text = paths[0].read_text()
    assert 'Secret' not in text
    assert json.loads(text)['runs'][0]['trajectory'] == '../trace.json'


def test_human_readable_numbers_and_coverage():
    from app.evaluation.batch_output import render_markdown, render_console
    from app.evaluation.batch import summarize_batch
    r = RunRecord('1','happy_path',1,{},report={'passed': True,'metrics':{'latency_ms':23475,'llm_call_count':2,'token_usage_reported_calls':2,'input_tokens':276540,'output_tokens':5492,'cached_input_tokens':247418,'cache_read_reported_calls':2}})
    summary = summarize_batch(BatchRecord('b','now',{},[r]))
    for text in (render_markdown(summary), render_console(summary)):
        assert 'Scenario checks passed' in text
        assert '1 of 1 (100%)' in text
        assert '23.5 s' in text
        assert '276,540' in text
        assert '89.5%' in text
        assert '"value"' not in text
        assert 'numerator' not in text
        assert 'Token usage reported for all 1 runs.' in text


def test_partial_usage_is_readable():
    from app.evaluation.batch_output import render_markdown
    from app.evaluation.batch import summarize_batch
    r = RunRecord('1','s',1,{},report={'metrics':{'llm_call_count':2,'token_usage_reported_calls':1,'input_tokens':100}})
    text = render_markdown(summarize_batch(BatchRecord('b','now',{},[r])))
    assert 'Unavailable' in text
    assert 'observed subtotal: 100' in text


def test_numbered_directories_are_ordered_and_do_not_overwrite(tmp_path):
    from app.evaluation.batch_output import allocate_report_directory
    first = allocate_report_directory(tmp_path)
    second = allocate_report_directory(tmp_path)
    assert first.name == '000001'
    assert second.name == '000002'
    (tmp_path / '000009').mkdir()
    (tmp_path / 'old-uuid').mkdir()
    assert allocate_report_directory(tmp_path).name == '000010'


def test_diagnostics_have_subheadings_instead_of_row_prefixes():
    from app.evaluation.batch_output import render_markdown
    from app.evaluation.batch import summarize_batch
    r = RunRecord('1','s',1,{},report={'metrics':{'per_agent':{'agent_a':{'llm_call_count':2}}},'checks':{'route':False}},events=[dict(type='tool.called',data={'tool':'get_weather_forecast'})])
    text = render_markdown(summarize_batch(BatchRecord('b','now',{},[r])))
    for heading in ('#### Execution outcomes', '#### Run accounting', '#### Successful run timing', '#### Unsuccessful run timing', '#### Usage coverage', '#### Tool reliability', '#### Scenario checks', '#### Agent A', '#### Get weather forecast'):
        assert heading in text
    assert 'Per agent /' not in text
    assert 'Check failures /' not in text
    assert 'Passed latency mean ms' not in text


def test_check_table_shows_passed_and_failed_counts():
    from app.evaluation.batch_output import render_markdown
    from app.evaluation.batch import summarize_batch
    records = [RunRecord('1','s',1,{},report={'checks':{'confirmed':True}}),
               RunRecord('2','s',2,{},report={'checks':{'confirmed':False}}),
               RunRecord('3','s',3,{},report={'checks':{}})]
    text = render_markdown(summarize_batch(BatchRecord('b','now',{},records)))
    assert '| Check | Passed | Failed |' in text
    assert '| Booking confirmed | 1 | 1 |' in text
    assert 'Confirmed failures' not in text
    assert 'Missing or inapplicable check results are excluded' in text
