"""标准件生成器:紧固件 / 运动件 / 结构件。
build123d 0.11 实现,面向原型与展示;尺寸按国标查表(工程近似),螺纹为简化环槽。
"""
import math
from build123d import (
    BuildPart, BuildSketch, BuildLine, Locations, PolarLocations, RegularPolygon,
    Circle, Polyline, Plane, Mode, Axis, Cone, Cylinder, Torus, Sphere, Box,
    extrude, fillet, chamfer, make_face,
)
from library import (
    Param, PartSpec, register, catalog,
    HEX_BOLT_TABLE, HEX_NUT_TABLE, WASHER_TABLE, SOCKET_CAP_TABLE, ISO10642_TABLE,
    M3_STANDOFF_HEX,
)


# ---------- 工具 ----------

def _hex_radius(s):
    """对边宽 s -> 外接圆半径。"""
    return s / math.sqrt(3)


def _thread_grooves(d, length, pitch, start=0.0, count=None):
    """在光杆上刻简化螺纹环槽(装饰用,不是真实牙型)。"""
    if count is None:
        count = max(1, int(length / pitch))
    for i in range(count):
        z = start + pitch * 0.5 + i * pitch
        if z > length - pitch * 0.4:
            break
        with Locations((0, 0, z)):
            Torus(major_radius=d / 2, minor_radius=pitch * 0.28, mode=Mode.SUBTRACT)


def _cyl(d, h, z=0.0, mode=Mode.ADD):
    with Locations((0, 0, z + h / 2)):
        Cylinder(radius=d / 2, height=h, mode=mode)


def _hex(s, h, z=0.0):
    sk = BuildSketch(Plane.XY.offset(z))
    with sk:
        RegularPolygon(_hex_radius(s), 6, major_radius=True)
    extrude(sk.sketch, amount=h)


def _hex_socket(sk_size, depth, z, mode=Mode.SUBTRACT):
    """内六角孔。"""
    sk = BuildSketch(Plane.XY.offset(z))
    with sk:
        RegularPolygon(_hex_radius(sk_size), 6, major_radius=True)
    extrude(sk.sketch, amount=-depth, mode=mode)


def _rot(x, y, a):
    return (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))


# ---------- 紧固件 ----------

def build_hex_bolt(d=8, l=40, grade="8.8"):
    s, k = HEX_BOLT_TABLE[d]
    with BuildPart() as p:
        _hex(s, k)
        _cyl(d, l, z=k)
        _thread_grooves(d, l, pitch=max(0.8, d * 0.2), start=k,
                        count=int(l * 0.7 / max(0.8, d * 0.2)))
        try:
            chamfer(p.edges().group_by(Axis.Z)[0], length=min(0.4, s * 0.05))
        except Exception:
            pass
        try:
            chamfer(p.edges().group_by(Axis.Z)[-1], length=min(0.5, d * 0.08))
        except Exception:
            pass
    return p.part


def build_hex_nut(d=8):
    s, m = HEX_NUT_TABLE[d]
    with BuildPart() as p:
        _hex(s, m)
        _cyl(d * 0.84, m, mode=Mode.SUBTRACT)
        try:
            for e in p.edges().group_by(Axis.Z)[:2]:
                chamfer(e, length=min(0.4, m * 0.12))
        except Exception:
            pass
    return p.part


def build_washer(d=8):
    d1, d2, h = WASHER_TABLE[d]
    with BuildPart() as p:
        _cyl(d2, h)
        _cyl(d1, h, mode=Mode.SUBTRACT)
    return p.part


def build_socket_cap(d=6, l=25):
    dk, k, sk = SOCKET_CAP_TABLE[d]
    with BuildPart() as p:
        _cyl(dk, k)
        _cyl(d, l, z=k)
        try:
            chamfer(p.edges().group_by(Axis.Z)[0], length=min(0.4, k * 0.1))
        except Exception:
            pass
        _hex_socket(sk, k * 0.62, k * 0.62)
        _thread_grooves(d, l, pitch=max(0.7, d * 0.17), start=k,
                        count=int(l * 0.6 / max(0.7, d * 0.17)))
    return p.part


def build_countersunk_socket(d=6, l=25):
    dk, k, sk = ISO10642_TABLE[d]
    with BuildPart() as p:
        Cone(bottom_radius=dk / 2, top_radius=d * 0.55, height=k)
        _cyl(d, l, z=k)
        _thread_grooves(d, l, pitch=max(0.7, d * 0.17), start=k,
                        count=int(l * 0.6 / max(0.7, d * 0.17)))
        _hex_socket(sk, k * 0.62, k * 0.62)
    return p.part


def build_wing_nut(d=6):
    s, m = HEX_NUT_TABLE[d]
    w = s * 2.4
    with BuildPart() as p:
        _hex(s, m * 1.15)
        _cyl(d * 0.84, m * 1.15, mode=Mode.SUBTRACT)
        for sx in (-1, 1):
            with Locations((sx * (s / 2 + w * 0.30), 0, m * 0.55)):
                Box(w * 0.62, m * 0.5, m * 1.15)
        for sx in (-1, 1):
            with Locations((sx * (s / 2 + w * 0.30), 0, m * 0.55)):
                Cylinder(radius=m * 0.34, height=m * 1.15, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
    return p.part


# ---------- 运动件 ----------

def _involute_points(rb, r_outer, n=16):
    """渐开线齿廓采样点(从基圆到外圆)。"""
    pts = [(rb, 0.0)]
    t = 0.0
    while len(pts) < n:
        t += 0.06
        x = rb * (math.cos(t) + t * math.sin(t))
        y = rb * (math.sin(t) - t * math.cos(t))
        if math.hypot(x, y) > r_outer:
            break
        pts.append((x, y))
    if len(pts) < 3:
        return [(rb, 0.0), (r_outer, 0.0), (r_outer, r_outer * 0.35)]
    return pts


def build_spur_gear(m=2, teeth=20, width=10, bore=6):
    """模数制直齿轮(20° 压力角,渐开线近似)。"""
    teeth = int(teeth)
    m = float(m)
    width = float(width)
    bore = float(bore)
    r_pitch = m * teeth / 2
    r_outer = r_pitch + m
    r_root = r_pitch - 1.25 * m
    rb = r_pitch * math.cos(math.radians(20))
    pitch_angle = 2 * math.pi / teeth
    with BuildPart() as p:
        with BuildSketch() as s:
            with Locations((0, 0)):
                Circle(r_root)
            for i in range(teeth):
                pts = _involute_points(rb, r_outer)
                left = [(x, -y) for x, y in pts]
                poly = [_rot(x, y, i * pitch_angle) for x, y in (pts + left[::-1])]
                with BuildLine():
                    Polyline(*poly, close=True)
                make_face()
            if bore > 0.4:
                with Locations((0, 0)):
                    Circle(bore / 2, mode=Mode.SUBTRACT)
        extrude(amount=width)
        try:
            fillet(p.edges().filter_by(Axis.Z), radius=min(m * 0.3, width * 0.3))
        except Exception:
            pass
    return p.part


def build_bearing_608():
    """608 深沟球轴承(8×22×7)外观近似:内外圈 + 7 球。"""
    OD, ID, W = 22.0, 8.0, 7.0
    ball_d = 3.97
    pitch = 15.0
    with BuildPart() as p:
        _cyl(OD, W)
        _cyl(OD - 4.4, W, mode=Mode.SUBTRACT)
        _cyl(12.4, W)
        _cyl(ID, W, mode=Mode.SUBTRACT)
        with PolarLocations(pitch / 2, 7):
            Sphere(radius=ball_d / 2)
    return p.part


def build_shaft(d=8, l=60, flat=False):
    """光轴(可选单侧扁位)。"""
    with BuildPart() as p:
        _cyl(d, l)
        try:
            chamfer(p.edges().group_by(Axis.Z)[0], length=min(0.5, d * 0.08))
            chamfer(p.edges().group_by(Axis.Z)[-1], length=min(0.5, d * 0.08))
        except Exception:
            pass
        if flat:
            with Locations((d / 2 - d * 0.08, 0, l * 0.4)):
                Box(d * 0.16, d, l * 0.5, mode=Mode.SUBTRACT)
    return p.part


# ---------- 结构件 ----------

def build_standoff(height=15, bore=3.0):
    """M3 六角铜柱:对边 5.5,中心通孔。"""
    s = M3_STANDOFF_HEX
    with BuildPart() as p:
        _hex(s, height)
        _cyl(bore, height, mode=Mode.SUBTRACT)
        try:
            for e in p.edges().group_by(Axis.Z)[:2]:
                chamfer(e, length=min(0.3, s * 0.05))
        except Exception:
            pass
    return p.part


# ---------- 打印件 ----------

def build_hex_plate(width=60, length=80, height=5, cell=6, wall=1.2):
    """蜂窝镂空板:六边形蜂窝网格,减重/装饰。"""
    width = float(width); length = float(length); height = float(height)
    cell = float(cell); wall = float(wall)
    a = cell * 0.87 - wall * 0.5          # 孔内切圆半径(留壁厚)
    if a <= 0.2:
        a = 0.2
    sx = cell * 3 ** 0.5                  # 横向间距
    sy = cell * 1.5                       # 纵向间距
    off = sx / 2
    with BuildPart() as p:
        with Locations((0, 0, height / 2)):
            Box(width, length, height)
        rows = int(length / sy) + 2
        cols = int(width / sx) + 2
        for r in range(rows):
            for c in range(cols):
                x = (c - cols / 2) * sx
                y = (r - rows / 2) * sy + (c % 2) * off
                if abs(x) > width / 2 + sx or abs(y) > length / 2 + sy:
                    continue
                sk = BuildSketch(Plane.XY.offset(height))
                with sk:
                    RegularPolygon(a, 6)
                extrude(sk.sketch, amount=-height, mode=Mode.SUBTRACT)
    return p.part


def build_extruder_support(plate_w=50, plate_h=67, thick=10, bridge_depth=35, slot_rad=8):
    """3D 打印机热端安装支架(移植自 adam-urbanczyk/cadquery-models,结构简化)。
    主板 + 两翼 + 前伸桥板 + 三角支撑 + 热端卡槽 + 安装孔。
    """
    plate_w = float(plate_w); plate_h = float(plate_h); thick = float(thick)
    bridge_depth = float(bridge_depth); slot_rad = float(slot_rad)
    bridge_h = 10.0
    with BuildPart() as p:
        # 主板
        with Locations((0, 0, thick / 2)):
            Box(plate_w, plate_h, thick)
        # 底部两翼
        for sx in (-1, 1):
            with Locations((sx * (plate_w / 2 + 2), -plate_h / 2 + 5, thick / 2)):
                Box(14, 10, thick)
        # 桥板(前伸)
        with Locations((0, plate_h / 2 + bridge_h / 2, 0)):
            Box(plate_w, bridge_h, bridge_depth)
        # 三角支撑(桥板下方)
        with BuildSketch(Plane.YZ) as ts:
            with BuildLine():
                Polyline((plate_h / 2, 0), (plate_h / 2 + 16, 0),
                         (plate_h / 2, -16), close=True)
            make_face()
        extrude(ts.sketch, amount=plate_w / 2, both=True)
        # 热端卡槽:圆孔 + 上方开口
        with Locations((0, plate_h / 2 + bridge_h, 0)):
            Cylinder(radius=slot_rad, height=bridge_depth, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
        with Locations((0, plate_h / 2 + bridge_h / 2, 0)):
            Box(slot_rad * 1.6, bridge_h + 1, bridge_depth + 1, mode=Mode.SUBTRACT)
        # 桥板顶部两个 M4 预钻孔
        for hx in (-16, 16):
            with Locations((hx, plate_h / 2 + bridge_h, 0)):
                Cylinder(radius=1.85, height=bridge_depth, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
        # 主板四角 M3 预钻孔 + 沉孔
        for hx, hy in ((-plate_w / 2 + 6, -plate_h / 2 + 6), (plate_w / 2 - 6, -plate_h / 2 + 6),
                       (-plate_w / 2 + 6, plate_h / 2 - 6), (plate_w / 2 - 6, plate_h / 2 - 6)):
            with Locations((hx, hy, thick / 2)):
                Cylinder(radius=1.25, height=thick + 2, mode=Mode.SUBTRACT)
            with Locations((hx, hy, thick - 2.5)):
                Cylinder(radius=2.6, height=5, mode=Mode.SUBTRACT)
    return p.part


# ---------- 注册 ----------

register(PartSpec(
    id="hex_bolt", name="六角头螺栓", category="紧固件",
    desc="半牙六角头螺栓,对边宽/头厚自动查表",
    standard="GB/T 5783(尺寸工程近似)",
    params=[
        Param("d", "公称直径", 8, kind="options", options=[3, 4, 5, 6, 8, 10, 12, 16, 20]),
        Param("l", "公称长度", 40, min=8, max=150, step=1),
        Param("grade", "性能等级", "8.8", kind="options", options=["4.8", "8.8", "10.9"]),
    ],
    build=build_hex_bolt,
))

register(PartSpec(
    id="hex_nut", name="六角螺母", category="紧固件",
    desc="普通六角螺母",
    standard="GB/T 6170(尺寸工程近似)",
    params=[
        Param("d", "公称直径", 8, kind="options", options=[3, 4, 5, 6, 8, 10, 12, 16, 20]),
    ],
    build=build_hex_nut,
))

register(PartSpec(
    id="washer", name="平垫圈", category="紧固件",
    desc="A 级平垫圈,内外径/厚度自动查表",
    standard="GB/T 97.1(尺寸工程近似)",
    params=[
        Param("d", "配套螺纹", 8, kind="options", options=[3, 4, 5, 6, 8, 10, 12, 16, 20]),
    ],
    build=build_washer,
))

register(PartSpec(
    id="socket_cap", name="内六角圆柱头螺钉", category="紧固件",
    desc="内六角圆柱头螺钉",
    standard="GB/T 70.1(尺寸工程近似)",
    params=[
        Param("d", "公称直径", 6, kind="options", options=[3, 4, 5, 6, 8, 10, 12]),
        Param("l", "公称长度", 25, min=6, max=120, step=1),
    ],
    build=build_socket_cap,
))

register(PartSpec(
    id="countersunk_socket", name="内六角沉头螺钉", category="紧固件",
    desc="90° 沉头内六角螺钉",
    standard="ISO 10642(尺寸工程近似)",
    params=[
        Param("d", "公称直径", 6, kind="options", options=[3, 4, 5, 6, 8, 10, 12]),
        Param("l", "公称长度", 25, min=6, max=120, step=1),
    ],
    build=build_countersunk_socket,
))

register(PartSpec(
    id="wing_nut", name="蝶形螺母", category="紧固件",
    desc="手拧蝶形螺母,3D 打印常用",
    standard="非标(参考 GB/T 62)",
    params=[
        Param("d", "公称直径", 6, kind="options", options=[4, 5, 6, 8, 10]),
    ],
    build=build_wing_nut,
))

register(PartSpec(
    id="spur_gear", name="直齿轮", category="运动件",
    desc="模数制渐开线直齿轮(20° 压力角,近似齿形)",
    standard="GB/T 1357 模数制(齿形近似)",
    params=[
        Param("m", "模数", 2, min=0.5, max=5, step=0.25),
        Param("teeth", "齿数", 20, min=8, max=80, step=1),
        Param("width", "齿宽", 10, min=2, max=60, step=1),
        Param("bore", "中心孔径", 6, min=0, max=60, step=0.5),
    ],
    build=build_spur_gear,
))

register(PartSpec(
    id="bearing_608", name="608 轴承", category="运动件",
    desc="608 深沟球轴承 8×22×7,外观近似",
    standard="608(结构近似,非选型依据)",
    params=[],
    build=build_bearing_608,
))

register(PartSpec(
    id="shaft", name="光轴", category="运动件",
    desc="两端倒角的光轴,可选单侧扁位",
    standard="通用",
    params=[
        Param("d", "直径", 8, min=3, max=50, step=0.5),
        Param("l", "长度", 60, min=10, max=300, step=1),
        Param("flat", "带扁位", False, kind="options", options=[False, True]),
    ],
    build=build_shaft,
))

register(PartSpec(
    id="standoff", name="六角铜柱", category="结构件",
    desc="M3 PCB 六角支柱,对边 5.5,中心通孔",
    standard="通用 PCB 支柱",
    params=[
        Param("height", "高度", 15, min=5, max=50, step=1),
        Param("bore", "孔径", 3.0, min=1.0, max=5.0, step=0.1),
    ],
    build=build_standoff,
))

register(PartSpec(
    id="hex_plate", name="蜂窝镂空板", category="打印件",
    desc="六边形蜂窝网格板,减重/装饰",
    standard="通用(蜂窝参数自定义)",
    params=[
        Param("width", "宽", 60, min=10, max=300, step=1),
        Param("length", "长", 80, min=10, max=300, step=1),
        Param("height", "厚度", 5, min=1, max=30, step=0.5),
        Param("cell", "蜂窝边长", 6, min=2, max=30, step=0.5),
        Param("wall", "壁厚", 1.2, min=0.6, max=5, step=0.1),
    ],
    build=build_hex_plate,
))

register(PartSpec(
    id="extruder_support", name="热端安装支架", category="打印件",
    desc="3D 打印机热端支架:主板+两翼+桥板+三角支撑+卡槽(移植自 cadquery-models)",
    standard="移植 adam-urbanczyk/cadquery-models(结构简化)",
    params=[
        Param("plate_w", "板宽", 50, min=30, max=100, step=1),
        Param("plate_h", "板高", 67, min=40, max=120, step=1),
        Param("thick", "板厚", 10, min=5, max=20, step=1),
        Param("bridge_depth", "桥板深", 35, min=15, max=70, step=1),
        Param("slot_rad", "卡槽半径", 8, min=4, max=16, step=0.5),
    ],
    build=build_extruder_support,
))
