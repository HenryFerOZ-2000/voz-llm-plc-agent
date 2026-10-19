"""GUI tests keep user history independent from their generated records."""
def test_gui_fixture_uses_temporary_history(app,project_root,tmp_path):
    assert app.history_storage_path==tmp_path/'gui_history.json'
    assert not app.history_storage_path.is_relative_to(project_root/'generated_code')
    assert app.history_records==[]
