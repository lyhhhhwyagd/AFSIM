from mcp.server.fastmcp import FastMCP
from pathlib import Path
from datetime import datetime

# --- 脚本片段构建器 ---
class ScriptBuilder:
    ORDER = [
        "physical", "aero", "antenna", "sensor", "processor",
        "platform_type", "weapon_effects", "weapon", "platform"
    ]
    def __init__(self):
        self.reset()

    def reset(self):
        self.sections   = {k: [] for k in self.ORDER}
        self.registered = set()

    def add(self, kind: str, snippet: str, name: str | None = None):
        # 用 (kind,name) 去重；name 为空时退化为全文去重
        key = (kind, name or snippet)
        if key in self.registered:
            return
        self.registered.add(key)
        self.sections[kind].append(snippet.rstrip() + "\n")

    def render(self) -> str:
        return "\n".join(line for k in self.ORDER for line in self.sections[k])

#把它当作 system_prompt 传给 FastMCP
# 创建 MCP 服务实例
mcp = FastMCP()

builder = ScriptBuilder()

# ---------- 物理特征 ----------
@mcp.tool()
def define_radar_signature(name: str, constant_dbsm: float) -> str:
    """
    定义雷达截面积 (RCS) 常量
    """
    snippet = f"""radar_signature {name}
   constant {constant_dbsm} m^2
end_radar_signature
"""
    builder.add("physical", snippet)
    return snippet

# ---------- 传感器 ----------
@mcp.tool()
def create_radar_sensor(name: str, one_m2_range_nm: float, max_range_nm: float) -> str:
    """
    创建雷达传感器模块
    """
    snippet = f"""sensor {name} WSF_RADAR_SENSOR
   one_m2_detect_range {one_m2_range_nm} nm
   maximum_range {max_range_nm} nm
end_sensor
"""
    builder.add("sensor", snippet)
    return snippet

# ---------- PROCESSOR ----------
@mcp.tool()
def create_script_processor(name: str, body: str) -> str:
    """
    创建脚本处理器，body 包含 on_update 等逻辑
    """
    snippet = f"""processor {name} WSF_SCRIPT_PROCESSOR
{body}
end_processor
"""
    builder.add("processor", snippet)
    return snippet

# ---------- 平台类型 ----------
@mcp.tool()
def create_platform_type(name: str,
                          mover: str,
                          sensors: list[str] = None,
                          weapons: list[str] = None,
                          processors: list[str] = None) -> str:
    """
    定义通用平台类型，包含 mover、sensors、weapons、processors
    """
    sensors = sensors or []
    weapons = weapons or []
    processors = processors or []
    lines = [f"platform_type {name} WSF_PLATFORM"]
    lines.append(f"   mover {mover}\n   end_mover")
    for s in sensors:
        lines.append(f"   sensor {s.lower()} {s}\n   end_sensor")
    for w in weapons:
        lines.append(f"   weapon {w.lower()} {w}\n   end_weapon")
    for p in processors:
        lines.append(f"   processor {p.lower()} {p}\n   end_processor")
    lines.append("end_platform_type")
    snippet = "\n".join(lines) + "\n"
    builder.add("platform_type", snippet)
    return snippet

# ---------- 武器毁伤效果 ----------
@mcp.tool()
def create_weapon_effects(name: str, max_radius_m: float, pk: float) -> str:
    """
    定义武器毁伤效果
    """
    snippet = f"""weapon_effects {name} WSF_GRADUATED_LETHALITY
   radius_and_pk {max_radius_m} m {pk}
end_weapon_effects
"""
    builder.add("weapon_effects", snippet)
    return snippet

# ---------- 武器 ----------
@mcp.tool()
def create_weapon(name: str,
                  launched_platform_type: str,
                  effects: str,
                  quantity: int = 4) -> str:
    """
    定义显式武器，指定发射后平台类型和毁伤效果
    """
    snippet = f"""weapon {name} WSF_EXPLICIT_WEAPON
   launched_platform_type {launched_platform_type}
   weapon_effects {effects}
   quantity {quantity}
end_weapon
"""
    builder.add("weapon", snippet)
    return snippet

# ---------- 平台实例 ----------
@mcp.tool()
def create_platform(name: str,
                    platform_type: str,
                    side: str,
                    lat: str,
                    lon: str,
                    altitude: str = "0 ft") -> str:
    """
    创建平台实例，设置位置与阵营
    """
    snippet = f"""platform {name} {platform_type}
   position {lat} {lon} altitude {altitude}
   side {side}
end_platform
"""
    builder.add("platform", snippet)
    return snippet

# ---------- 终结脚本 ----------
@mcp.tool()
def finalize_script(save: bool = True, reset: bool = False) -> str:
    script = builder.render()
    if save:
        Path(...).write_text(script, "utf-8")
    if reset:
        builder.sections = {k: [] for k in builder.ORDER}
        builder.registered.clear()
    return script

@mcp.tool()
def calculate_bmi(weight_kg: float, height_m: float) -> float:
    """根据体重（kg）和身高（m）计算BMI"""
    return weight_kg / (height_m ** 2)

# ---------- 启动服务 ----------
if __name__ == "__main__":
    # 使用 stdio 与 MCP 客户端通信
    mcp.run(transport="stdio")
