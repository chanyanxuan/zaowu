"""本地冒烟测试:构建全部标准件默认参数,导出 STEP。"""
import sys, os, traceback
sys.path.insert(0, r"C:\Users\Administrator\Desktop\text2cad")
import library.parts as lp  # noqa
from library import PART_REGISTRY
from build123d.exporters3d import export_step

OUT = r"C:\Users\Administrator\Desktop\text2cad\proto_out\library_test"
os.makedirs(OUT, exist_ok=True)
fails = []
for pid, spec in PART_REGISTRY.items():
    try:
        kwargs = {p.key: p.default for p in spec.params}
        part = spec.build(**kwargs)
        path = os.path.join(OUT, f"{pid}.step")
        export_step(part, path)
        print(f"OK   {pid:20s} volume={part.volume:8.0f} step={os.path.getsize(path)//1024}KB")
    except Exception as e:
        fails.append(pid)
        print(f"FAIL {pid:20s} {e}")
        traceback.print_exc()
print("\n失败:", fails if fails else "无")
