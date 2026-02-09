try:
    from .cleanup import find_cleanup_candidates, is_cleanup_candidate
    from .facade import HAS_OBSTORE, RemoteFileFacade, SupportsFileId
except ModuleNotFoundError as exc:
    if exc.name not in {"obstore", "pydantic"}:
        raise

    __all__ = []

    def __getattr__(name: str) -> object:
        if name in {"RemoteFileFacade", "SupportsFileId", "find_cleanup_candidates", "is_cleanup_candidate"}:
            msg = "brussels.files requires optional dependencies. Install with `pip install brussels[files]`."
            raise ModuleNotFoundError(msg)
        msg = f"module 'brussels.files' has no attribute '{name}'"
        raise AttributeError(msg)
else:
    __all__ = ["SupportsFileId", "find_cleanup_candidates", "is_cleanup_candidate"]
    if HAS_OBSTORE:
        __all__ += ["RemoteFileFacade"]
    else:
        del RemoteFileFacade

        def __getattr__(name: str) -> object:
            if name == "RemoteFileFacade":
                msg = (
                    "brussels.files.RemoteFileFacade requires the optional dependency 'obstore'. "
                    "Install with `pip install brussels[files]`."
                )
                raise ModuleNotFoundError(msg)
            msg = f"module 'brussels.files' has no attribute '{name}'"
            raise AttributeError(msg)
