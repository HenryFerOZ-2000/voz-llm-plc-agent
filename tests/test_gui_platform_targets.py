from gui_helpers import normalize_platform_targets, platform_label


def test_siemens_and_openplc_are_selected_in_parallel() -> None:
    assert normalize_platform_targets("Siemens + OpenPLC") == [
        "SIEMENS_SCL_V18",
        "OPENPLC_ST"
    ]


def test_all_platforms_include_siemens() -> None:
    assert normalize_platform_targets("Todas") == [
        "SIEMENS_SCL_V18",
        "OPENPLC_ST",
        "CODESYS_ST"
    ]
    assert platform_label("SIEMENS_SCL_V18") == "Siemens TIA V18"

