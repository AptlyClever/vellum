# Vellum Lookdev Worker — UE project Python startup.
#
# Unreal loads Content/Python/init_unreal.py for the editor session and keeps the
# module alive. That is the supported sticky lifetime for slate tick + HTTP.
# Do NOT treat -ExecutePythonScript as the long-lived worker (it tears down after main).

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_boot():
    try:
        import unreal  # type: ignore
    except Exception:
        return None

    boot_path = Path(unreal.Paths.project_saved_dir()) / "VellumCapture" / "vellum_ue_worker_boot.py"
    if not boot_path.is_file():
        print(f"[VellumWorker] init_unreal: missing boot script {boot_path}", flush=True)
        return None

    name = "vellum_ue_worker_boot"
    if name in sys.modules:
        return sys.modules[name]

    spec = importlib.util.spec_from_file_location(name, str(boot_path))
    if spec is None or spec.loader is None:
        print(f"[VellumWorker] init_unreal: cannot load {boot_path}", flush=True)
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    mod = _load_boot()
    if mod is None:
        return
    start = getattr(mod, "start_worker", None)
    if not callable(start):
        print("[VellumWorker] init_unreal: boot has no start_worker()", flush=True)
        return
    try:
        start()
    except Exception as exc:  # noqa: BLE001
        print(f"[VellumWorker] init_unreal: start_worker failed: {exc}", flush=True)


main()
