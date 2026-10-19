"""A virtual selection must never accept a physical PG/PC route."""
import pytest
import gui
from plc_target_dialog import PlcTargetDialog


@pytest.mark.parametrize('kind,interface,allowed',[
    ('PLCSIM_ADVANCED','Intel Wi-Fi',False),
    ('PLCSIM_ADVANCED','Siemens PLCSIM Virtual Ethernet Adapter',True),
    ('PHYSICAL_PLC','Intel Wi-Fi',True),
])
def test_selected_kind_and_interface_are_consistent(app,monkeypatch,kind,interface,allowed):
    warnings=[];monkeypatch.setattr(gui.messagebox,'showwarning',lambda *a,**k:warnings.append(a))
    dialog=PlcTargetDialog(app,{'target_type':'PLCSIM_ADVANCED'}, {})
    try:
        dialog.kind.set(kind)
        dialog.instances=[{'instance_id':0,'instance_name':'Banco','addresses':['192.168.0.1']}]
        dialog.instance_box.configure(values=['Banco']);dialog.instance_box.current(0)
        dialog.connections=[{'configuration_mode':'PN/IE','pc_interface':interface,'pc_interface_number':1,'target_interfaces':['1 X1']}]
        dialog.route_box.configure(values=['Intel Wi-Fi']);dialog.route_box.current(0)
        dialog.port.set('1 X1');dialog.address.set('192.168.0.1');dialog.name.set('Banco')
        dialog.accept()
        assert (dialog.result is not None)==allowed
        assert bool(warnings)==(not allowed)
    finally:
        if not dialog.closed:dialog.cancel()
