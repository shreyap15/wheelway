import sys
from pathlib import Path

# Put hardware/ on the path so `import wheelway_bridge` resolves without the
# upstream submodule (these tests never touch the camera/perception packages).
_HARDWARE = Path(__file__).resolve().parents[2]
if str(_HARDWARE) not in sys.path:
    sys.path.insert(0, str(_HARDWARE))
