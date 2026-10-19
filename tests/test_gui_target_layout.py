import json
from pathlib import Path
import pytest
import gui


@pytest.mark.parametrize('size',[(1920,1080),(1600,900)])
def test_primary_actions_fit_supported_viewport(app,size,tmp_path):
    app.geometry(f'{size[0]}x{size[1]}');app.update_idletasks();app._apply_responsive_layout();app.update_idletasks()
    rows=[]
    for widget in (app.execute_command_button,app.execute_and_load_button,app.download_plc_button,app.normal_voice_button):
        assert widget.winfo_manager()=='grid'
        width=widget.winfo_width();assert width>=300
        font=widget.cget('font')
        assert max(font.measure(line) for line in widget.cget('text').splitlines())<=width-12
        rows.append({'text':widget.cget('text'),'width':width,'height':widget.winfo_height()})
    (tmp_path/'layout.json').write_text(json.dumps({'size':size,'actions':rows}))
