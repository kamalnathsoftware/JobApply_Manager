from app.adapters.base import SiteAdapter

_REGISTRY: dict[str, str] = {
    "naukri": "app.adapters.naukri:NaukriAdapter",
}


def get_adapter_class(site: str) -> type[SiteAdapter]:
    import importlib

    try:
        module, cls = _REGISTRY[site].split(":")
    except KeyError:
        raise ValueError(f"No adapter registered for site '{site}'") from None
    return getattr(importlib.import_module(module), cls)
