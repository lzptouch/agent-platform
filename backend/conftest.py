"""让 pytest 能直接 import `app` 包（项目根目录加入 sys.path）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
