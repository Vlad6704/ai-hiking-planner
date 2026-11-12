from app.evaluation.batch import BatchRecord, RunRecord, summarize_batch


def test_accounting_and_partial_usage():
    good = dict(passed=True, trip_result=dict(status="confirmed", route_id="r", equipment_items=[]), metrics=dict(llm_call_count=2, token_usage_reported_calls=1, input_tokens=100), checks={"ok": True})
    records = [RunRecord("1", "happy", 1, {}, started=True, report=good), RunRecord("2", "happy", 2, {})]
    result = summarize_batch(BatchRecord("b", "now", {}, records))
    m = result["overall"]
    assert m["scenario_pass_rate"]["value"] == .5
    assert m["incomplete_run_count"]["value"] == 1
    assert m["input_tokens"]["value"] is None
    assert m["input_tokens"]["observed_subtotal"] == 100


def test_latency_and_weighted_tools():
    records = []
    for i, latency in enumerate([10, 20, 90]):
        events = [dict(type="tool.called", data={"tool": "weather"}) for _ in range(i + 1)]
        if i == 0:
            events.append(dict(type="tool.failed", data={"tool": "weather"}))
        records.append(RunRecord(str(i), "s", i, {}, started=True, report=dict(passed=True, metrics=dict(latency_ms=latency)), events=events))
    m = summarize_batch(BatchRecord("b", "now", {}, records))["overall"]
    assert m["latency_mean_ms"]["value"] == 40
    assert m["latency_median_ms"]["value"] == 20
    assert m["tool_failure_rate"]["value"] == 1 / 6


def test_receipt_error_and_repeatability_groups():
    report = dict(passed=True, trip_result=dict(status='confirmed', route_id='r', reservation_id='one', equipment_items=['b', 'a']), metrics={})
    a = RunRecord('a','s',1,{},started=True,report=report)
    b = RunRecord('b','s',2,{},started=True,report={**report, 'error':'private'}, error={'code':'execution_failed'})
    receipt = dict(type='tool.completed',data=dict(tool='create_tour_reservation',output=dict(status='success',data={'reservation_id':'one'})))
    a.events = [receipt]
    b.events = [receipt]
    summary = summarize_batch(BatchRecord('b','now',{},[a,b]))
    assert summary['overall']['runtime_error_count']['value'] == 1
    assert summary['overall']['scenario_pass_rate']['value'] == .5
    assert summary['overall']['confirmed_booking_count']['value'] == 2
    assert summary['comparison_groups'][0]['successful_repeatability']['value'] == .5
    b.context = {'model':'different'}
    assert len(summarize_batch(BatchRecord('b','now',{},[a,b]))['comparison_groups']) == 2


def test_inactive_agent_does_not_erase_complete_usage():
    metrics = dict(llm_call_count=0, token_usage_reported_calls=0, input_tokens=None, output_tokens=None, cache_read_reported_calls=0, cache_write_reported_calls=0)
    r = RunRecord('1','s',1,{},report={'metrics':metrics})
    assert summarize_batch(BatchRecord('b','now',{},[r]))['overall']['input_tokens']['value'] == 0


def test_receipt_survives_without_final_result_and_cache_subtotal():
    event = dict(type='tool.completed',data=dict(tool='create_tour_reservation',output=dict(status='success',data={'reservation_id':'TR-12345678'})))
    r = RunRecord('1','s',1,{},started=True,error={'code':'execution_failed'},events=[event], report={'passed':False,'metrics':{'llm_call_count':2,'cache_read_reported_calls':1,'cached_input_tokens':None,'cached_input_tokens_observed':40}})
    summary = summarize_batch(BatchRecord('b','now',{},[r]))
    assert summary['overall']['confirmed_booking_count']['value'] == 1
    assert summary['runs'][0]['booking_receipt']['reservation_id'] == 'TR-12345678'
    assert summary['overall']['cached_input_tokens']['value'] is None
    assert summary['overall']['cached_input_tokens']['observed_subtotal'] == 40


def test_runtime_error_codes_preserve_known_failures_without_raw_text():
    records = [RunRecord(str(i),'s',i,{},report={'error':error}) for i,error in enumerate(['deadlock','peer_timeout','delivery_failed: C:/private/path','secret C:/private/path'])]
    codes = summarize_batch(BatchRecord('b','now',{},records))['overall']['error_codes']
    assert codes == {'deadlock':1,'peer_timeout':1,'delivery_failed':1,'runtime_error':1}
