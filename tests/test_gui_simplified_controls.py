import json
import gui
from test_gui_full_map_window import temp_map


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def test_eight_duplicate_controls_are_absent_from_sidebar(app):
    forbidden={'Abrir mapa I/O','Guardar mapa I/O','Agregar variable','Editar variable','Bloquear variable','Desbloquear variable','Eliminar variable','Marcar como libre'}
    labels={w.cget('text') for w in descendants(app.left_panel) if isinstance(w,gui.ctk.CTkButton)}
    assert not forbidden.intersection(labels)


def test_execute_and_load_remains_visible_in_normal_mode(app):
    app.work_mode_var.set('Normal');app._refresh_voice_button_states()
    assert app.execute_and_load_button.winfo_manager()!=''
    assert app.execute_and_load_button.cget('command')==app.execute_and_load_to_plc


def test_full_map_edit_uses_its_own_selection(app,temp_map,monkeypatch):
    app.io_tree.selection_set(app.io_tree.get_children()[0])
    window=gui.FullIOMapWindow(app)
    try:
        window.tree.selection_set('%QX8.1')
        class Dialog:
            def __init__(self,parent,title,data,**kwargs):self.result={**data,'description':'Editada en mapa completo'}
        monkeypatch.setattr(gui,'VariableEditorDialog',Dialog)
        monkeypatch.setattr(window,'wait_window',lambda d:None)
        window.edit_variable()
        variables={v['name']:v for v in json.loads(temp_map.read_text())['variables']}
        assert variables['I_Start']['description']=='Inicio'
        assert variables['Q_Alarm']['description']=='Editada en mapa completo'
    finally:window.destroy()


def test_full_map_has_library_operations(app,temp_map):
    window=gui.FullIOMapWindow(app)
    try:
        labels={w.cget('text') for w in descendants(window) if isinstance(w,gui.ctk.CTkButton)}
        assert {'Nuevo mapa','Abrir archivo…','Validar mapa','Sincronizar con TIA','Importar desde TIA'}.issubset(labels)
    finally:window.destroy()


def test_open_map_file_imports_validated_copy(app,temp_map,tmp_path,monkeypatch):
    source=tmp_path/'external.json';source.write_bytes(temp_map.read_bytes());before=source.read_bytes()
    monkeypatch.setattr(app,'project_root',tmp_path/'isolated')
    monkeypatch.setattr(gui.filedialog,'askopenfilename',lambda **k:str(source))
    app.open_map_file()
    assert app.io_map_path!=source
    assert json.loads(app.io_map_path.read_text())['variables']==json.loads(before)['variables']
    assert source.read_bytes()==before
