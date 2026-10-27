from pathlib import Path
import importlib.util
import pytest

# Historical campaign snapshot is versioned; runtime/ is intentionally local.
PATH = Path(__file__).resolve().parent/'fixtures/campaign_generation_classification_20261026.py'

def classify(error, stage):
    spec=importlib.util.spec_from_file_location('campaign_classification',PATH)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.classify_generation_exception(error,stage)

def test_blocked_assignment_is_terminal_failure_and_cannot_trigger_technical_retry():
    result=classify(ValueError('IO_ASSIGNMENT_BLOCKED'),'io_allocation')
    assert result=={'final_status':'FAIL','failure_stage':'io_allocation','failure_category':'IO_ALLOCATION_FAILURE'}

@pytest.mark.parametrize('error',[RuntimeError('Connection error'),TimeoutError('Request timed out')])
def test_service_errors_before_semantics_are_technical(error):
    assert classify(error,'parse')['final_status']=='INFRASTRUCTURE_ERROR'

def test_generation_exception_is_not_retried_as_a_service_failure():
    assert classify(ValueError('unsupported parameter'),'generate')['final_status']=='FAIL'

def test_invalid_semantic_response_is_not_a_network_failure():
    result=classify(ValueError('invalid JSON'),'parse')
    assert result['final_status']=='FAIL' and result['failure_category']=='SEMANTIC_FAILURE'
