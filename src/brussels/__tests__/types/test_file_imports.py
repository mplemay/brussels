from __future__ import annotations

import builtins
import importlib
import sys

import pytest


def test_file_module_import_error_guides_files_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def fake_import(name, globals_=None, locals_=None, fromlist=(), level=0):
        if name == "obstore.store" or name.startswith("obstore"):
            msg = "No module named 'obstore'"
            raise ModuleNotFoundError(msg)
        return original_import(name, globals_, locals_, fromlist, level)

    for module_name in [
        "brussels.types.file",
        "brussels.types.file.metadata",
        "brussels.types.file.remote_file",
        "brussels.types.file.storage",
        "brussels.types.file.helpers",
    ]:
        sys.modules.pop(module_name, None)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match=r"pip install brussels\[file\]"):
        importlib.import_module("brussels.types.file")
