import inspect

import pybop

for cls_name in ("GITTPulseFit", "GITTFit"):
    cls = getattr(pybop, cls_name)
    print("=" * 70)
    print(cls_name, "->", cls.__module__)
    doc = inspect.getdoc(cls) or ""
    print(doc[:1500])
    try:
        print("--- __init__ signature ---")
        print(inspect.signature(cls.__init__))
    except Exception as e:
        print("no signature:", e)

print("=" * 70)
try:
    from pybop.applications import gitt_methods
    print("gitt_methods:", [n for n in dir(gitt_methods) if not n.startswith("_")])
    print((inspect.getdoc(gitt_methods) or "")[:800])
except Exception as e:
    print("gitt_methods import failed:", e)
