from .cleanup import find_cleanup_candidates, is_cleanup_candidate
from .facade import HAS_OBSTORE, RemoteFileFacade

__all__ = ["find_cleanup_candidates", "is_cleanup_candidate"]

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
