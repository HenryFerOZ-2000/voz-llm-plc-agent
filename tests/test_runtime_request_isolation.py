import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor


def test_concurrent_runtime_calls_keep_their_own_request_and_result(tmp_path,monkeypatch):
    import plcsim_runtime as module
    (tmp_path/'plcsim_runtime_bridge').mkdir()
    peer=tmp_path/'peer.py'
    peer.write_text('import sys,json,time\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text())\ntime.sleep(.1)\nPath(r["result_path"]).write_text(json.dumps({"status":"ECHO","marker":r["marker"]}))\n')
    monkeypatch.setattr(module,'build_runtime_bridge',lambda *_a,**_k:{'built':True,'exe_path':sys.executable})
    original=subprocess.run
    barrier=threading.Barrier(2)
    def launch(command,**kwargs):
        barrier.wait(timeout=5)
        return original([command[0],str(peer),command[1]],**kwargs)
    monkeypatch.setattr(module.subprocess,'run',launch)
    config={'api_dll_path':'unused','instance_name':'TESIS_PLC_SIM','windows_adapter_match':'unused','timeout_seconds':5}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(module.run_runtime_bridge,'runtime_status',tmp_path,config,{'marker':n}) for n in (1,2)]
        reports=[future.result(timeout=10) for future in futures]
    assert [r['marker'] for r in reports]==[1,2]
