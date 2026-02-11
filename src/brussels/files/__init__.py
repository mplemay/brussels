try:
    from .cleanup import find_cleanup_candidates, is_cleanup_candidate
except ModuleNotFoundError as exc:
    if exc.name != "pydantic":
        raise

    __all__ = []

    def __getattr__(name: str) -> object:
        if name in {"find_cleanup_candidates", "is_cleanup_candidate"}:
            msg = "brussels.files requires optional dependencies. Install with `pip install brussels[files]`."
            raise ModuleNotFoundError(msg)
        msg = f"module 'brussels.files' has no attribute '{name}'"
        raise AttributeError(msg)
else:
    __all__ = ["find_cleanup_candidates", "is_cleanup_candidate"]
