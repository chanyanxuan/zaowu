"""参数化标准件库:数据模型 + 国标查表。
每个标准件 = PartSpec(元信息 + 参数定义) + build 函数(参数 -> build123d Part)。
构建走现有 cadgen 运行时,零 LLM 调用、零积分。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class Param:
    key: str
    label: str
    default: Any
    kind: str = "number"          # number | options
    unit: str = "mm"
    min: float = None
    max: float = None
    step: float = None
    options: List[Any] = None
    desc: str = ""


@dataclass
class PartSpec:
    id: str
    name: str
    category: str
    desc: str
    standard: str                 # 依据的标准/近似说明
    params: List[Param] = field(default_factory=list)
    build: Callable = None        # fn(**params) -> build123d Part


PART_REGISTRY: Dict[str, PartSpec] = {}
CATEGORY_ORDER = ["紧固件", "运动件", "结构件", "打印件"]


def register(spec: PartSpec):
    PART_REGISTRY[spec.id] = spec
    return spec


def catalog() -> List[dict]:
    """返回目录(不含 build 函数,给前端用)。"""
    out = []
    for cat in CATEGORY_ORDER:
        parts = [p for p in PART_REGISTRY.values() if p.category == cat]
        out.append({
            "category": cat,
            "parts": [{
                "id": p.id, "name": p.name, "desc": p.desc, "standard": p.standard,
                "params": [{k: v for k, v in vars(x).items()} for x in p.params],
            } for p in parts],
        })
    return out


# ---------- 国标查表(工程近似值,面向原型与展示) ----------

# GB/T 5783 六角头螺栓:M -> (对边宽 s, 头厚 k)
HEX_BOLT_TABLE = {3: (5.5, 2.0), 4: (7.0, 2.8), 5: (8.0, 3.5), 6: (10.0, 4.0),
                  8: (13.0, 5.3), 10: (17.0, 6.4), 12: (19.0, 7.5), 16: (24.0, 10.0),
                  20: (30.0, 12.5)}

# GB/T 6170 六角螺母:M -> (对边宽 s, 厚度 m)
HEX_NUT_TABLE = {3: (5.5, 2.4), 4: (7.0, 3.2), 5: (8.0, 4.0), 6: (10.0, 5.0),
                 8: (13.0, 6.5), 10: (17.0, 8.0), 12: (19.0, 10.0), 16: (24.0, 13.0),
                 20: (30.0, 16.0)}

# GB/T 97.1 平垫圈:M -> (内径 d1, 外径 d2, 厚度 h)
WASHER_TABLE = {3: (3.2, 7.0, 0.5), 4: (4.3, 9.0, 0.8), 5: (5.3, 10.0, 1.0),
                6: (6.4, 12.0, 1.6), 8: (8.4, 16.0, 1.6), 10: (10.5, 20.0, 2.0),
                12: (13.0, 24.0, 2.5), 16: (17.0, 30.0, 3.0), 20: (21.0, 37.0, 3.0)}

# GB/T 70.1 内六角圆柱头螺钉:M -> (头径 dk, 头高 k, 内六角 s)
SOCKET_CAP_TABLE = {3: (5.5, 3.0, 2.5), 4: (7.0, 4.0, 3.0), 5: (8.5, 5.0, 4.0),
                    6: (10.0, 6.0, 5.0), 8: (13.0, 8.0, 6.0), 10: (16.0, 10.0, 8.0),
                    12: (18.0, 12.0, 10.0)}

# ISO 10642 内六角沉头螺钉:M -> (头径 dk, 头高 k, 内六角 s)  [近似:dk=2d, k=0.5d]
ISO10642_TABLE = {d: (round(d * 2.0, 1), round(d * 0.5, 1),
                      {3: 2.0, 4: 2.5, 5: 3.0, 6: 4.0, 8: 5.0, 10: 6.0, 12: 8.0}[d])
                  for d in (3, 4, 5, 6, 8, 10, 12)}

# M3 六角铜柱(PCB 支柱,常见规格)
M3_STANDOFF_HEX = 5.5            # 对边宽
