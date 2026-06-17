import os
import sys

from PyInstaller import compat
from PyInstaller.utils import hooks as hookutils


hiddenimports = ["numpy", "cv2.cv2"]
hiddenimports += hookutils.collect_submodules("cv2", filter=lambda name: name != "cv2.load_config_py2")
excludedimports = ["cv2.load_config_py2"]

datas = hookutils.collect_data_files(
    "cv2",
    include_py_files=True,
    includes=[
        "config.py",
        f"config-{sys.version_info[0]}.{sys.version_info[1]}.py",
        "config-3.py",
        "load_config_py3.py",
    ],
)

binaries = hookutils.collect_dynamic_libs("cv2")
if compat.is_win:
    binaries = [
        (src, dst)
        for src, dst in binaries
        if "opencv_videoio_ffmpeg" not in os.path.basename(src).lower()
    ]

module_collection_mode = "py"
