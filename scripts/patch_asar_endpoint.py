"""Byte-patch etne app.asar: neutralize the baked-in localhost:8085 endpoint.

NEXT_PUBLIC_ENTE_ENDPOINT was leaked into the Sep-16 build as
"http://localhost:8085". Replace each quoted literal with `void 0`
padded to the same length so JSON/discovery offsets stay intact and
the expression `?? void 0` yields undefined -> api.ente.com + CF worker.
"""
from pathlib import Path
import shutil, sys

ASAR = Path(r"E:\development\ente-custom\desktop\dist\win-unpacked\resources\app.asar")
OLD = b'"http://localhost:8085"'
NEW = b'void 0' + b' ' * (len(OLD) - len(b'void 0'))
assert len(OLD) == len(NEW), (len(OLD), len(NEW))

data = ASAR.read_bytes()
count = data.count(OLD)
print(f"occurrences: {count}")
if count == 0:
    sys.exit("nothing to patch")
shutil.copy2(ASAR, ASAR.with_suffix(".asar.bak"))
ASAR.write_bytes(data.replace(OLD, NEW))
print(f"patched {count}; backup at app.asar.bak")
