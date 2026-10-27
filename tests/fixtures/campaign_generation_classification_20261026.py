"""Use the product GUI's distinction between service failure and generation failure."""
def classify_generation_exception(error, stage):
    text=str(error).lower()
    external=any(marker in text for marker in ('timeout','timed out','connection','connect','network','rate limit',
                                               'ratelimit','429','502','503','504','service unavailable','authentication','401','ssl'))
    if str(error)=='IO_ASSIGNMENT_BLOCKED':
        return {'final_status':'FAIL','failure_stage':'io_allocation','failure_category':'IO_ALLOCATION_FAILURE'}
    if stage in ('parse','asr') and external:
        return {'final_status':'INFRASTRUCTURE_ERROR','failure_stage':stage,'failure_category':'INFRASTRUCTURE_ERROR'}
    return {'final_status':'FAIL','failure_stage':stage,
            'failure_category':'SEMANTIC_FAILURE' if stage=='parse' else 'CODEGEN_FAILURE'}
