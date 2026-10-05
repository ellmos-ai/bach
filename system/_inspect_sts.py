import sqlite_transit_sync
print("version:", getattr(sqlite_transit_sync, "__version__", "unknown"))
for name in sorted(dir(sqlite_transit_sync)):
    obj = getattr(sqlite_transit_sync, name)
    if not name.startswith("_"):
        print(name, type(obj).__name__)
        try:
            print("   doc:", (obj.__doc__ or "")[:120].replace("\n", " "))
        except Exception:
            pass
        if callable(obj) and not isinstance(obj, type):
            import inspect
            try:
                print("   sig:", str(inspect.signature(obj))[:120])
            except Exception:
                pass
        if isinstance(obj, type):
            import inspect
            try:
                print("   init:", str(inspect.signature(obj.__init__))[:200])
            except Exception:
                pass
