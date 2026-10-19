"""Production C# source lifetime: preserve manual files and clean up on failure."""
import subprocess
from pathlib import Path
import pytest
import tia_openness as tia
from utils import get_project_root


@pytest.fixture(scope='module')
def lifecycle_probe(tmp_path_factory):
    root=get_project_root()
    built=tia.build_openness_bridge(root)
    assert built['built'],built
    folder=tmp_path_factory.mktemp('native_source_probe')
    exe=folder/'probe.exe'
    result=subprocess.run([str(tia.DEFAULT_COMPILER),'/nologo','/target:exe',
        f'/out:{exe}',str(root/'tests/fixtures/NativeSourceLifecycleProbe.cs')],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return exe,Path(built['exe_path'])


@pytest.mark.parametrize('scenario',['success','generate_failure','create_failure','delete_failure'])
def test_native_source_lifetime_preserves_manual_sources(lifecycle_probe,tmp_path,scenario):
    exe,bridge=lifecycle_probe
    result=subprocess.run([str(exe),str(bridge),str(tmp_path),scenario],
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
