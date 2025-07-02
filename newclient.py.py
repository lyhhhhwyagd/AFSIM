import asyncio
import sys
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI
import json

load_dotenv()  # load environment variables from .env


def format_tools_for_llm(tool) -> str:
    """对tool进行格式化
    Returns:
        格式化之后的tool描述
    """
    args_desc = []
    if "properties" in tool.inputSchema:
        for param_name, param_info in tool.inputSchema["properties"].items():
            arg_desc = (
                f"- {param_name}: {param_info.get('description', 'No description')}"
            )
            if param_name in tool.inputSchema.get("required", []):
                arg_desc += " (required)"
            args_desc.append(arg_desc)

    return f"Tool: {tool.name}\nDescription: {tool.description}\nArguments:\n{chr(10).join(args_desc)}"


class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.client = AsyncOpenAI(
            base_url="https://api.deepseek.com/v1",
            api_key="****************************",
        )
        self.model = "deepseek-chat"
        self.messages = []
        self.tools = []

    async def connect_to_server(self, server_script_path: str):
        """连接MCP服务器"""
        server_params = StdioServerParameters(
            command="python",
            args=[server_script_path],
            env=None
        )

        self.stdio, self.write = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()

        # 列出可用工具
        response = await self.session.list_tools()
        tools = response.tools
        print("\n服务器中可用的工具：", [tool.name for tool in tools])

        self.tools = [{
            "type": 'function',
            "function": {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
        } for tool in tools]
        tools_description = "\n".join([format_tools_for_llm(tool) for tool in tools])
        # 修改系统prompt
        system_prompt = (
            """你是一个专业的AFSIM脚本编写与前端编程助手，严格遵守以下指令：
                        【核心原则】
                        1. 生成内容必须与样板脚本格式100%一致，包括所有字段、缩进、注释和关键字
                        2. 当用户提供预定义性质(如光学特征)时，必须完整保留所有原有性质字段
                        3. 禁止添加/删除/修改任何未明确要求的字段
                        4. 严格遵循样板的结构顺序和语法规范

                        【执行流程】
                        1. 深度解析样板脚本结构（特别注意字段层次关系）：
                            - 物理特征 → 传感器 → 处理器 → 平台类型 → 实体定义
                            - 每个模块内的字段顺序（如：icon→特征签名→mover→weapon）
                        2. 对用户请求执行完整性检查：
                            a. 验证所有必需字段存在性（见下方字段清单）
                            b. 交叉检查字段引用关系（如光学特征名是否匹配）
                            c. 确保数值单位/格式完全一致
                        3. 生成时采用字段级复制策略：
                            - 对未修改部分：直接复制样板字段（含注释）
                            - 对修改部分：仅替换指定内容，保持周边结构不变

                        【关键字段完整性清单 - 飞机平台必须包含】
                        ✅ 平台类型声明: platform_type [名称] WSF_PLATFORM
                        ✅ 特征签名三件套（严格保留顺序）:
                            infrared_signature [名称]
                            optical_signature [名称]  # 用户自定义时必须保留
                            radar_signature [名称]
                        ✅ 运动系统: mover WSF_AIR_MOVER...end_mover
                        ✅ 武器系统: weapon [ID] [类型]...end_weapon
                        ✅ 处理器: processor [ID] [类型]...end_processor
                        ✅ 结束标记: end_platform_type

                        【实体定义必须包含】
                        ✅ 平台声明: platform [名称] [类型]
                        ✅ 跟踪目标: track platform [目标] end_track
                        ✅ 阵营声明: side [颜色]
                        ✅ 初始航向: heading [值] degrees
                        ✅ 完整路由定义: route...end_route
                        ✅ 结束标记: end_platform

                        【错误防护机制】
                        ✋ 当检测字段缺失时：立即中止生成并返回错误码：
                            MISSING_FIELD:[字段名]（示例：MISSING_FIELD:optical_signature）
                        ✋ 当特征签名未定义时：返回 UNDEFINED_SIGNATURE:[签名名]

                        【输出规范】
                        ▶ 仅返回可执行的完整脚本
                        ▶ 禁止任何解释性文字/注释，如```等符号
                        ▶ 保留样板所有注释和空行格式
            【样板脚本】           
## 物理特征定义
+ 如红外信号特征、光学特征、雷达特征。
+ 在所有代码块的外面定义，在platform或platform_type中引用。
+ 类似于全局变量。

### 红外信号特征定义

infrared_signature BOMBER_INFRARED_SIG  # 定义名为"BOMBER_INFRARED_SIG"的红外特征
   constant 10 watts/steradian         # 设置恒定的红外辐射强度为10瓦特/球面度
end_infrared_signature


+ infrared_signature是脚本关键字，表明定义的是红外特征。
+ BOMBER_INFRARED_SIG是用户自己取的名字。

### 光学特征定义

optical_signature BOMBER_OPTICAL_SIG  # 轰炸机的光学特征签名定义
   constant 10 m^2                     # 恒定光学横截面积10平方米
end_optical_signature


### 雷达特征定义

radar_signature BOMBER_RADAR_SIG  # 轰炸机雷达散射截面(RCS)特征定义
   state default  # 默认状态（可定义不同状态如：起落架收放、武器舱开关等不同RCS状态）
      
      # 极坐标RCS数据表（分贝平方米/dBsm）
      inline_table dbsm 24 5  # 数据格式：24行x5列（方位角x俯仰角）
                -90.0  -30.0   0.0   30.0   90.0  # 俯仰角(°)：-90°(正下方)到90°(正上方)
        -180.0   20.0   20.0   0.0   20.0   20.0  # 第一行：方位角-180°时的各俯仰角RCS值
        -145.0   20.0   20.0   0.0   20.0   20.0  # 后续每行对应不同方位角的RCS分布
        -140.0   20.0   20.0  40.0   20.0   20.0  
        -135.0   20.0   20.0  40.0   20.0   20.0  
        -130.0   20.0   20.0   0.0   20.0   20.0
         -95.0   20.0   20.0   0.0   20.0   20.0
         -90.0   20.0   20.0  40.0   20.0   20.0  # 方位角-90°（左侧）的RCS分布
         -85.0   20.0   20.0   0.0   20.0   20.0
         -50.0   20.0   20.0   0.0   20.0   20.0
         -45.0   20.0   20.0  40.0   20.0   20.0  # 前向45°方位角出现RCS峰值
         -35.0   20.0   20.0  40.0   20.0   20.0
         -30.0   20.0   20.0   0.0   20.0   20.0
          30.0   20.0   20.0   0.0   20.0   20.0
          35.0   20.0   20.0  40.0   20.0   20.0  # 前向35°方位角RCS峰值
          45.0   20.0   20.0  40.0   20.0   20.0
          50.0   20.0   20.0   0.0   20.0   20.0
          85.0   20.0   20.0   0.0   20.0   20.0
          90.0   20.0   20.0  40.0   20.0   20.0  # 方位角90°（右侧）的RCS分布
          95.0   20.0   20.0   0.0   20.0   20.0
         130.0   20.0   20.0   0.0   20.0   20.0
         135.0   20.0   20.0  40.0   20.0   20.0  # 后向45°方位角RCS峰值
         140.0   20.0   20.0  40.0   20.0   20.0
         145.0   20.0   20.0   0.0   20.0   20.0
         180.0   20.0   20.0   0.0   20.0   20.0  # 方位角180°（正后方）的RCS分布
      end_inline_table
end_radar_signature


+ radar_signature、state default、 inline_table dbsm均为AFSIM的关键字。

## 传感器定义
### 搜索雷达

# 定义搜索雷达系统（预警雷达）
# -------------------------------------------------------------------
# 天线方向图：矩形波束（旋转扫描天线）
antenna_pattern ACQ_RADAR_ANTENNA
   rectangular_pattern
      peak_gain             35 dB     # 主瓣最大增益35dB（高增益）
      minimum_gain         -10 db     # 最低旁瓣增益-10dB
      azimuth_beamwidth     10 deg    # 方位角波束宽度10度
      elevation_beamwidth   10 deg     # 俯仰角波束宽度10度（扇形波束）
   end_rectangular_pattern
end_antenna_pattern

# 搜索雷达传感器定义
# -------------------------------------------------------------------
# 主要功能：远程空中目标探测与跟踪（早期预警）
sensor ACQ_RADAR WSF_RADAR_SENSOR

   # 基本探测性能参数
   one_m2_detect_range   50 nm  # 对1m²目标探测距离50海里（约93km）
   maximum_range        150 nm   # 最大理论探测距离150海里（约278km）
   
   # 系统参数
   antenna_height         5 m    # 天线安装高度（影响地平线探测）
   frame_time            10 sec  # 扫描周期10秒（6rpm）
   
   # 扫描模式与范围
   scan_mode             azimuth_and_elevation  # 方位+俯仰扫描
   azimuth_scan_limits   -180 deg 180 deg      # 360度全方位扫描
   elevation_scan_limits    0 deg  50 deg      # 俯仰范围（地平线到50度）
   
   # 发射机参数
   transmitter
      antenna_pattern    ACQ_RADAR_ANTENNA  # 使用上述定义的天线
      power              1000 kw            # 峰值功率1000千瓦
      frequency          3000 mhz           # S波段（3GHz），大气穿透性好
      internal_loss         2 db            # 发射机内部损耗
   end_transmitter
   
   # 接收机参数
   receiver
      antenna_pattern    ACQ_RADAR_ANTENNA  # 同发射天线
      bandwidth             2 mhz           # 接收带宽2MHz
      noise_power        -160 dbw           # 接收机噪声功率（极低噪声）
      internal_loss         7 dB            # 接收机内部损耗
   end_receiver
   
   # 信号处理参数
   probability_of_false_alarm 1.0e-6  # 虚警概率：百万分之一
   required_pd 0.5            # 要求探测概率50%
   swerling_case 1            # 目标起伏模型（Swerling I，缓慢起伏）
   
   # 航迹处理参数
   hits_to_establish_track 3 5  # 建立航迹需要3-5次探测
   hits_to_maintain_track 1 5   # 维持航迹需要1-5次探测
   
   track_quality 0.6            # 航迹质量（战术预警级）
   
   # 可提供的数据报告
   reports_range      # 报告目标距离
   reports_bearing    # 报告目标方位
   reports_elevation  # 报告目标俯仰角
   reports_iff        # 报告IFF敌我识别
   
end_sensor


### 跟踪雷达

# 定义高精度跟踪雷达天线方向图
# -------------------------------------------------------------------
# 采用正弦（高斯）波束模型模拟现实雷达天线特性
antenna_pattern TTR_RADAR_ANTENNA
  sine_pattern
    peak_gain            35 dB        # 主瓣最大增益35dB（高定向天线）
    minimum_gain      -10.0 dB        # 最低增益值（旁瓣增益限制）
    azimuth_beamwidth    1 deg        # 方位角波束宽度1度（极高方位分辨率）
    elevation_beamwidth  1 deg        # 俯仰角波束宽度1度（极高俯仰分辨率）
  end_sine_pattern
end_antenna_pattern

# 定义目标跟踪雷达(TTR)传感器
# -------------------------------------------------------------------
# 高性能火控雷达，用于精确跟踪空中目标
sensor TTR_RADAR WSF_RADAR_SENSOR
   # 工作模式：多目标跟踪能力
   selection_mode                 multiple

   # 天线转动能力
   slew_mode                      azimuth_and_elevation      # 方位+俯仰双轴转动
   azimuth_slew_limits            -180 deg 180 deg          # 全向覆盖（360度）
   elevation_slew_limits          0.0 deg 80.0 deg          # 俯仰范围（地平线到近垂直）

   # 雷达基本性能模板（应用于所有工作模式）
   mode_template
      one_m2_detect_range            35.0 nm  # 对1m²RCS目标探测距离35海里（≈65km）
      maximum_range                 100.0 nm   # 最大理论探测距离100海里（约185km）

      antenna_height                 4.0 m     # 天线安装高度（用于计算地平线限制）

      # 发射机参数（高功率微波发射）
      transmitter
         antenna_pattern             TTR_RADAR_ANTENNA  # 应用上述天线模型
         power                       1000.0 kw           # 峰值功率1000千瓦（高功率）
         frequency                   9500 mhz            # X波段（9.5GHz），高精度
         internal_loss               2 db                # 发射电路损耗
      end_transmitter

      # 接收机参数（高灵敏度信号接收）
      receiver
         antenna_pattern             TTR_RADAR_ANTENNA  # 同发射天线
         bandwidth                   500.0 khz           # 接收带宽500kHz
         noise_power                 -160 dBw            # 接收机噪声功率（超低噪声）
         internal_loss               7 dB                # 接收电路损耗
      end_receiver

      # 探测性能参数
      probability_of_false_alarm     1.0e-6   # 虚警概率：百万分之一（高可靠性）
      required_pd                    0.5      # 所需检测概率：50%（基础值）
      swerling_case                  1        # 目标起伏模型：Swerling I型（缓慢起伏）

      # 测量数据输出能力
      reports_range                   # 能提供目标距离测量
      reports_bearing                # 能提供目标方位角测量
      reports_elevation               # 能提供目标俯仰角测量
      reports_velocity               # 能提供目标径向速度测量
   end_mode_template

   # 雷达工作模式1：目标截获（ACQUIRE）
   # -----------------------------------------------
   # 功能：在特定空域搜索并初步跟踪目标
   mode ACQUIRE
      maximum_request_count          1  # 同时处理的请求数（单目标截获）

      # 扫描模式与范围
      scan_mode                      azimuth_and_elevation  # 方位+俯仰扫描
      azimuth_scan_limits            -5 deg 5 deg          # ±5度方位扫描范围
      elevation_scan_limits          -5 deg 5 deg          # ±5度俯仰扫描范围
      frame_time                     2.0 sec               # 扫描周期2秒（中等更新率）

      # 航迹建立/维持条件
      hits_to_establish_track        3 5   # 建立航迹需要3-5次探测
      hits_to_maintain_track         1 3   # 维持航迹需要1-3次探测

      track_quality                  0.8   # 航迹质量（接近火控级但未达最优）
   end_mode

   # 雷达工作模式2：精确跟踪（TRACK）
   # -----------------------------------------------
   # 功能：对选定目标进行高精度跟踪（火控级）
   mode TRACK
      maximum_request_count          1  # 同时处理的请求数（单目标精确跟踪）

      # 扫描模式与范围
      scan_mode                      azimuth_and_elevation  # 方位+俯仰扫描
      azimuth_scan_limits            -1 deg 1 deg   # ±1度方位扫描范围（极窄）
      elevation_scan_limits          -1 deg 1 deg   # ±1度俯仰扫描范围（高精度）
      frame_time                     1.0 sec        # 扫描周期1秒（高更新率）

      # 航迹建立/维持条件（更严格）
      hits_to_establish_track        3 5   # 建立航迹需要3-5次探测
      hits_to_maintain_track         1 3   # 维持航迹需要1-3次探测

      track_quality                  1.0   # 最高航迹质量（满足导弹火控要求）
   end_mode
end_sensor




## 平台交战决策逻辑定义
+ 为飞机或导弹定义processor（处理器）。
+ 在示例中仅展示WSF_SCRIPT_PROCESSOR、WSF_GROUND_TARGET_FUSE、WSF_GUIDANCE_COMPUTER处理器。

### 轰炸机武器投放处理器

# 轰炸机武器投放处理器
# 功能：控制轰炸机在满足条件时自动投放GPS制导炸弹
processor BOMBER_WEAPON_RELEASE WSF_SCRIPT_PROCESSOR
   script_variables  // 声明处理器使用的变量
      string weaponName = "red_gps_bomb_1";  // 默认武器名称（红色GPS炸弹）
      string LARmeters = "lar_meters";       // 武器射程参数的键名（在auxdata中查找）
      Array<bool> tgt_engaged = Array<bool>(); // 记录各目标是否已被攻击的布尔数组
   end_script_variables
   
  # 绘制武器射程范围的可视化圆圈
  script void Draw()
     # 获取当前武器对象
     WsfWeapon tempWeapon = PLATFORM.Weapon(weaponName);
   
     # 检查武器是否有效且包含射程参数
     if (tempWeapon.IsValid() && tempWeapon.AuxDataExists(LARmeters))
     {
        # 创建绘图对象
        WsfDraw draw = WsfDraw();
      
        # 从武器数据中获取最大射程（单位：米）
        double range = tempWeapon.AuxDataDouble(LARmeters);
      
        # 设置绘图参数
        draw.SetDuration(3.0);        // 图形持续显示3秒
        draw.SetColor(0,1,0);        // 使用绿色(RGB:0,1,0)
        draw.SetEllipseMode("line"); // 绘制空心圆（非填充模式）
      
        # 开始绘制以平台为中心，射程为半径的圆圈
        draw.BeginCircle(0.0, range); // 0.0表示水平面，range是半径
        draw.Vertex(PLATFORM);       // 以当前平台位置为圆心
        draw.End();                  // 结束绘制 
     } // 结束有效性检查
  end_script
   
   on_initialize2  // 初始化时运行一次
      # 初始化所有目标的交战状态为"未攻击"
      for (int i = 0; i < PLATFORM.MasterTrackList().Count(); i = i + 1)
      {
         tgt_engaged[i] = false;  // 每个目标初始状态设为false
      } 
   end_on_initialize2
   
   # 自定义武器发射函数
   script bool fireWeapon (WsfTrack tTrack, string tWpn)
      bool shot = false;  // 发射成功标志
      
      # 获取武器对象并验证有效性
      WsfWeapon tempWeapon = PLATFORM.Weapon(tWpn);
      if (tempWeapon.IsValid() && tempWeapon.AuxDataDouble(LARmeters))
      {
         double tempRange = tempWeapon.AuxDataDouble(LARmeters);  // 从武器数据读取最大射程
         # 检查发射条件：射程内、有弹药、高度≥7620米（25000英尺）
         if (PLATFORM.GroundRangeTo(tTrack) < tempRange    // 目标在射程内
             && tempWeapon.QuantityRemaining() > 0         // 剩余弹药>0
             && PLATFORM.Altitude() >= 7620)               // 高度达标
             {
                shot = tempWeapon.FireSalvo(tTrack, 2);  // 齐射2枚炸弹
             } // 条件判断结束
      } // 有效性检查结束
   
      # 如果成功发射，记录日志
      if (shot)  
      {
         writeln(PLATFORM.Name(), " fired ", tWpn, " at ",
                 tTrack.TargetName(), " at time ", TIME_NOW);
      }
   
      return shot;  // 返回发射结果
   end_script
   
   # 主循环设置（每3秒执行一次on_update）
   update_interval 3.0 s  
   on_update  // 主更新循环
      # 遍历所有探测到的目标
      for (int i = 0; i < PLATFORM.MasterTrackList().Count(); i += 1)  
      {
         if ( !tgt_engaged[i])  // 只处理未攻击过的目标
         {
            Draw();  // 调用绘图函数
            
            WsfTrack tempTrack = PLATFORM.MasterTrackList().TrackEntry(i);  // 获取当前目标
            if (fireWeapon(tempTrack, weaponName))  // 尝试攻击
            {
               tgt_engaged[i] = true;  // 标记为已攻击
            } // 武器发射判断结束
         } // 未攻击目标判断结束
      } // 目标循环结束
   end_on_update
   
# 处理器定义结束
end_processor


+ processor、WSF_SCRIPT_PROCESSOR是AFSIM的关键字。
+ script_variables、on_initialize2、script是AFSIM的关键字。
+ WsfTrack是AFSIM的关键字。
+ update_interval、on_update是AFSIM的关键字。

### 防空导弹战术处理器

# 单发大型防空导弹战术处理器
# 功能：实现防空导弹系统的智能交战决策逻辑
processor SINGLE_LARGE_SAM_TACTICS WSF_TASK_PROCESSOR

   # 定义战术参数
   script_variables
      double launchRange = 20.0 * MATH.M_PER_NM();  # 导弹最大射程（20海里≈37km）
      double salvoSize   = 2;                       # 每次齐射发射导弹数量
      string weaponName  = "sam";                   # 使用的武器系统名称
   end_script_variables
   
   # 判断是否满足交战条件的函数
   script bool CanEngage()
      bool canEngage = false;  # 默认不可交战
      
      # 获取武器系统
      WsfWeapon sam = PLATFORM.Weapon(weaponName);
      
      # 检查交战条件
      if (sam.IsValid() &&                          # 武器有效
          sam.QuantityRemaining() >= salvoSize &&    # 弹药充足
          TRACK.Target().IsValid() &&                # 目标有效
          PLATFORM.GroundRangeTo(TRACK) < launchRange &&  # 目标在射程内
          WeaponsActiveFor(TRACK.TrackId()) < 1)     # 无其他武器攻击此目标
       {
          canEngage = true;  # 满足所有条件，允许交战
       }
       return canEngage;  # 返回交战判断结果
   end_script
   
///////////////////////////////////////////////////////////////////////////////
#                       状态机定义（有限状态机）
///////////////////////////////////////////////////////////////////////////////

   # 状态1：目标已探测（DETECTED）
   # 评估间隔：10秒
   evaluation_interval DETECTED 10 sec
   state DETECTED
      # 状态转移条件1：如果是友军目标则忽略
      next_state IGNORE
         return (TRACK.IFF_Friend());  # 通过IFF识别是否为友军
      end_next_state
      
      # 状态转移条件2：满足交战条件则准备交战
      next_state ENGAGE
         return CanEngage();  # 检查是否满足交战条件
      end_next_state
   end_state
   
   # 状态2：交战状态（ENGAGE）
   # 评估间隔：10秒
   evaluation_interval ENGAGE 10 sec
   state ENGAGE
      # 状态转移条件：执行射击操作后进入等待状态
      next_state WAIT
         return Fire(TRACK, "FIRE", weaponName, salvoSize, PLATFORM);  # 发射导弹
      end_next_state
   end_state
   
   # 状态3：等待状态（WAIT）
   # 评估间隔：10秒
   evaluation_interval WAIT 10 sec
   state WAIT
      # 状态转移条件：如果再次满足交战条件（如目标未被摧毁）
      next_state ENGAGE
         return CanEngage();  # 检查是否满足再次交战条件
      end_next_state
   end_state
   
   # 状态4：忽略状态（IGNORE）
   # 评估间隔：24小时（相当于永久忽略）
   evaluation_interval IGNORE 24 hr
   state IGNORE
   # 无状态转移条件（永久忽略此目标）
   end_state
   
# 处理器定义结束
end_processor

# 状态机工作流程说明：
# 1. 初始状态：DETECTED（目标已被探测）
# 2. 如果是友军目标 -> 转移到IGNORE（永久忽略）
# 3. 如果满足交战条件 -> 转移到ENGAGE（执行交战）
# 4. 在ENGAGE状态 -> 自动发射导弹并转移到WAIT（等待结果）
# 5. 在WAIT状态 -> 如果目标仍在且满足条件，重新转移到ENGAGE（再次攻击）
#
# 典型交战场景：
#   - 探测到目标 -> 检查是敌是友
#   - 确认敌方目标后检查射程和弹药状态
#   - 发射2枚导弹
#   - 等待10秒后检查目标是否被摧毁
#   - 若未被摧毁且仍在射程内，再次发射


## 平台类型定义
### 导弹平台类型定义
#### 红方GPS导弹

# 定义红色GPS炸弹的雷达截面积
# 值为1平方米（模拟常规弹药特征）
radar_signature RED_GPS_BOMB_1_RADAR_SIGNATURE
   constant 1 m^2
end_radar_signature

# 定义空气动力学特性
aero RED_GPS_BOMB_1_AERO WSF_AERO
   cd_zero_subsonic     0.100    # 亚音速阻力系数
   cd_zero_supersonic   0.40     # 超音速阻力系数
   mach_begin_cd_rise   0.800    # 阻力开始增大的马赫数
   mach_end_cd_rise     1.200    # 阻力达到峰值的马赫数
   mach_max_supersonic  2.000    # 最大模拟马赫数
   reference_area       0.059 m2 # 参考横截面积
   cl_max              10.400    # 最大升力系数
   aspect_ratio         4.000    # 展弦比
end_aero

##########################开始定义平台类型################################
# 定义武器平台类型（GPS制导炸弹）
platform_type RED_GPS_BOMB_1 WSF_PLATFORM
   icon jdam  # 使用JDAM炸弹图标
   radar_signature RED_GPS_BOMB_1_RADAR_SIGNATURE #使用上面定义的雷达特性

   # 移动器配置（非制导运动模型）
   mover WSF_UNGUIDED_MOVER
      aero RED_GPS_BOMB_1_AERO  # 应用上方定义的气动参数
      mass 500 lbs               # 质量500磅
      update_interval 0.5 s      # 运动计算间隔0.5秒
   end_mover

   # 制导计算机参数
   processor guidance_computer WSF_GUIDANCE_COMPUTER
      proportional_navigation_gain 10.0   # 比例导引系数
      velocity_pursuit_gain        10.0   # 速度追踪系数
      g_bias                        1.0   # 重力补偿系数
      maximum_commanded_g          25.0 g # 最大过载限制
      guidance_delay                0.0 sec # 制导响应延迟
   end_processor

   # 引信参数（空地弹触发机制）
   processor fuse WSF_GROUND_TARGET_FUSE
      maximum_time_of_flight 900 seconds # 最大飞行时间（15分钟）
   end_processor
end_platform_type

   # 武器毁伤效应定义（球形爆炸模式）
  weapon_effects RED_GPS_BOMB_1_EFFECTS WSF_SPHERICAL_LETHALITY
     allow_incidental_damage  # 允许附带损伤
     minimum_radius   25.0 m   # 最大毁伤半径（完全毁伤范围）
     maximum_radius   30.0 m   # 有效毁伤半径边界
     minimum_damage   0.1      # 边界处最小毁伤值
     maximum_damage   1.0      # 核心区域最大毁伤值
     threshold_damage 0.2      # 触发毁伤累积效应的阈值
     exponent         1.0      # 毁伤衰减指数（1.0=线性衰减）
  end_weapon_effects


+ radar_signature是AFSIM的关键字。
+ aero是AFSIM的关键字。
+ processor、WSF_UNGUIDED_MOVER、WSF_GUIDANCE_COMPUTER等是AFSIM的关键字。
+ WSF_GROUND_TARGET_FUSE是AFSIM的关键字。
+ weapon_effects、WSF_SPHERICAL_LETHALITY是AFSIM的关键字。

##### 导弹毁伤效应定义

# 武器毁伤效应定义（球形爆炸模式）
weapon_effects RED_GPS_BOMB_1_EFFECTS WSF_SPHERICAL_LETHALITY
   allow_incidental_damage  # 允许附带损伤
   minimum_radius   25.0 m   # 最大毁伤半径（完全毁伤范围）
   maximum_radius   30.0 m   # 有效毁伤半径边界
   minimum_damage   0.1      # 边界处最小毁伤值
   maximum_damage   1.0      # 核心区域最大毁伤值
   threshold_damage 0.2      # 触发毁伤累积效应的阈值
   exponent         1.0      # 毁伤衰减指数（1.0=线性衰减）
end_weapon_effects


#### 蓝方防空导弹

# 定义大型防空导弹
# -------------------------------------------------------------------
# 红外特征
infrared_signature LARGE_SAM_INFRARED_SIGNATURE
   constant 1 watts/steradian  # 恒定辐射强度：1瓦特/球面度
end_infrared_signature

# 光学特征
optical_signature  LARGE_SAM_OPTICAL_SIGNATURE
   constant 1 m^2  # 恒定光学横截面积：1平方米
end_optical_signature

# 雷达特征
radar_signature    LARGE_SAM_RADAR_SIGNATURE
   constant 1 m^2  # 恒定雷达截面积(RCS)：1平方米
end_radar_signature

# 定义大型防空导弹平台类型
# -------------------------------------------------------------------
# 平台类型：大型防空导弹（模拟SA-10类似系统）
platform_type LARGE_SAM WSF_PLATFORM
  icon SA-10_Missile  # 使用SA-10导弹图标

  # 应用特征签名
  infrared_signature LARGE_SAM_INFRARED_SIGNATURE
  optical_signature  LARGE_SAM_OPTICAL_SIGNATURE
  radar_signature    LARGE_SAM_RADAR_SIGNATURE

  # 运动控制
  mover WSF_STRAIGHT_LINE_MOVER
     average_speed                 2643.0 kts  # 平均速度2643节（约马赫4）
     maximum_lateral_acceleration  20.0 g      # 最大横向加速度20G
     guidance_mode                 lead_pursuit  # 制导模式：前置追踪
  end_mover

  # 引信设置
  processor fuse WSF_AIR_TARGET_FUSE
     max_time_of_flight_to_detonate  37.0 sec  # 最大飞行时间37秒
  end_processor

  # 导引头设置（完美跟踪器）
  processor seeker WSF_PERFECT_TRACKER
     update_interval  0.5 s  # 0.5秒更新间隔（每秒更新2次）
  end_processor
end_platform_type

# 定义导弹毁伤效果
# -------------------------------------------------------------------
# 渐变杀伤效应（随距离增加，杀伤概率下降）
weapon_effects LARGE_SAM_EFFECT WSF_GRADUATED_LETHALITY
   radius_and_pk  100.0 m  0.7  # 100米半径内杀伤概率70%
end_weapon_effects

# 定义防空导弹武器系统
# -------------------------------------------------------------------
# 武器类型：大型防空导弹
weapon LARGE_SAM WSF_EXPLICIT_WEAPON
   launched_platform_type LARGE_SAM  # 发射后生成上述导弹平台
   maximum_request_count 10          # 最大同时可发射数量（10枚）
   
   weapon_effects LARGE_SAM_EFFECT   # 应用上述毁伤效果
   
   quantity               4          # 导弹库存量（4枚）
   
   # 发射参数
   firing_delay           0.5 sec    # 发射准备时间0.5秒
   salvo_interval         5.0 sec    # 齐射间隔时间5秒
   
   # 发射装置转动参数
   slew_mode              azimuth_and_elevation      # 方位角和俯仰角可转动
   azimuth_slew_limits    -180.0 deg 180.0 deg      # 方位角转动范围：±180度
   elevation_slew_limits  10.0 deg  70.0 deg        # 俯仰角范围：10-70度（防空导弹典型范围）
end_weapon


### 飞机平台类型定义
+ 在platform_type代码块中指定飞机平台类型的物理特征、运动系统、武器系统、投弹逻辑处理器。


platform_type BOMBER WSF_PLATFORM  # 定义名为BOMBER的平台类型，继承基础平台WSF_PLATFORM
   icon bomber  # 在地图/界面上显示为轰炸机图标
   
   # 平台特征信号  --使用上面定义过的物理特性
   infrared_signature BOMBER_INFRARED_SIG  # 红外特征
   optical_signature  BOMBER_OPTICAL_SIG   # 光学特征
   radar_signature    BOMBER_RADAR_SIG     # 雷达反射特征
   
   # 运动系统配置
   mover WSF_AIR_MOVER  # 使用AFSIM预设的空中平台移动模型 
   end_mover
   
   # 武器系统配置
   weapon red_gps_bomb_1 RED_GPS_BOMB_1  # 定义武器ID和武器类型
      maximum_request_count 2  # 单次攻击最多同时投掷2枚炸弹
      quantity 4               # 总载弹量4枚
   end_weapon
   
   # 武器处理器（投弹逻辑）
   processor fire-em BOMBER_WEAPON_RELEASE  # 使用专门的轰炸机武器投放处理器
   end_processor
   
# 注释掉的自动攻击指令（示例）：
#   execute at_time 510 sec absolute  # 在模拟开始后第510秒执行
#      Weapon("red_gps_bomb_1").FireSalvo(MasterTrackList().TrackEntry(0), 2);  # 向第一个目标发射2枚
#      Weapon("red_gps_bomb_1").FireSalvo(MasterTrackList().TrackEntry(1), 2);  # 向第二个目标发射2枚
#   end_execute

end_platform_type




### 汽车平台类型定义

platform_type CAR WSF_PLATFORM
   icon car
   infrared_signature  VEHICLE_INFRARED_SIGNATURE
   optical_signature  VEHICLE_OPTICAL_SIGNATURE
   radar_signature  VEHICLE_RADAR_SIGNATURE
   mover WSF_GROUND_MOVER
   end_mover
end_platform_type


### 坦克平台类型定义

platform_type TANK WSF_PLATFORM
   icon tank
   mover WSF_GROUND_MOVER
   end_mover
end_platform_type


### 卫星平台类型定义

platform_type SATELLITE WSF_PLATFORM
   icon satellite
   mover WSF_SPACE_MOVER
   end_mover
end_platform_type


### 船平台类型定义

platform_type SHIP WSF_PLATFORM
   icon ship
   mover WSF_SURFACE_MOVER
   end_mover
end_platform_type


### 防空导弹基地平台类型定义

# 定义单基地大型防空导弹系统平台类型
# -------------------------------------------------------------------
# 平台类型：一体化防空导弹系统
platform_type SINGLE_LARGE_SAM WSF_PLATFORM
   icon TWIN_BOX                     # 使用双雷达图标
   category ENGAGEMENT               # 分类为火力打击系统

   # 特征签名设置（使用车辆标准签名）
   infrared_signature    VEHICLE_INFRARED_SIGNATURE
   optical_signature     VEHICLE_OPTICAL_SIGNATURE
   radar_signature       VEHICLE_RADAR_SIGNATURE

   # 航迹管理器配置
   track_manager
      filter FILTER_TACTICS end_filter  # 使用预设战术过滤器处理目标信息
   end_track_manager

   # 通信系统1：指挥网络（与上级指挥所通信）
   comm cmdr_net TEAM_DATALINK
      network_name <local:slave>     # 本地网络从节点
      internal_link data_mgr         # 连接内部数据处理器
      internal_link task_mgr         # 连接内部任务处理器
   end_comm

   # 通信系统2：下属网络（与同级或友军单位通信）
   comm sub_net TEAM_DATALINK
      network_name <local:master>    # 本地网络主节点
      internal_link data_mgr         # 连接内部数据处理器
      internal_link task_mgr         # 连接内部任务处理器
   end_comm

   # 系统活动区域定义（防空作战范围）
   zone full_kinematic
      circular
         maximum_altitude 30 km     # 最大作战高度30公里
         maximum_radius   25 nm      # 最大作战半径25海里(≈46km)
   end_zone

   # 传感器1：搜索雷达（警戒/目标获取）
   sensor acq ACQ_RADAR
      on                            # 默认开启
      internal_link data_mgr         # 连接数据处理器
      ignore_same_side              # 忽略同阵营目标（避免误伤友军）
   end_sensor

   # 传感器2：跟踪雷达（火控级精确跟踪）
   sensor ttr TTR_RADAR
      # 默认参数继承自先前定义的TTR_RADAR
   end_sensor

   # 武器系统配置：大型防空导弹
   weapon sam LARGE_SAM
      quantity 16                   # 初始装载量16枚导弹
   end_weapon

   # 数据处理中心：管理所有雷达探测数据
   processor data_mgr WSF_TRACK_PROCESSOR
      purge_interval 60 seconds      # 60秒清理一次无效航迹
   end_processor

   # 任务管理中心：执行战术决策
   processor task_mgr SINGLE_LARGE_SAM_TACTICS

   end_processor
end_platform_type

# 系统功能分析：
# 1. 一体化作战单元：
#    - 整合搜索雷达(acq)和跟踪雷达(ttr)
#    - 配备16枚防空导弹(sam)
#
# 2. 战场感知能力：
#    - 最大探测高度30km（覆盖高空目标）
#    - 46km作战半径（中远程防空系统）
#
# 3. 指挥通信系统：
#    cmdr_net：向上级指挥所报告（从节点）
#    sub_net：向下属单元发送指令（主节点）
#
# 4. 作战流程：
#    acq雷达发现目标 -> 数据处理器创建航迹 -> 
#    任务处理器评估威胁 -> ttr雷达精确跟踪 -> 
#    导弹发射拦截
#
# 典型战术配置：
#   任务处理器(task_mgr)加载SINGLE_LARGE_SAM_TACTICS战术脚本


## 平台实体定义
### 导弹实体定义
+ 使用上面定义的物理特征、平台类型、毁伤效应。来创建导弹实体。


# 武器实体定义（使用GPS制导航弹）
weapon RED_GPS_BOMB_1 WSF_EXPLICIT_WEAPON
   launched_platform_type RED_GPS_BOMB_1  # 指定平台
   weapon_effects RED_GPS_BOMB_1_EFFECTS  # 指定毁伤效果
   aux_data
      # 关键参数：最大投射距离，在飞机投弹逻辑中进行了使用。  
      double lar_meters = 18520
   end_aux_data
end_weapon


### 飞机实体定义
+ 使用上面定义的平台类型，创建飞机实体。


# 定义轰炸机平台 bomber_1
platform bomber_1 BOMBER  # 使用上面定义的平台类型BOMBER
   
   # 预设跟踪目标
   track platform tank_1 end_track  # 跟踪目标1：坦克1
   track platform tank_2 end_track  # 跟踪目标2：坦克2

   # 所属阵营
   side red  # 设定为红方
   
   # 初始航向
   heading 270 degrees  # 航向270°
   
   # 飞行路线定义
   route  # 开始定义飞行路径
      # 起点位置（佛罗里达州杰克逊维尔西北部）
      position 30:05:54.78n 80:07:48.80w altitude 30000.00 ft  # 北纬30°05'54.78", 西经80°07'48.80"
         speed 500 mph  # 初始速度500英里/小时
      
      # 航路点1（佛罗里达州东部）
      position 30:05:28.867n 81:30:28.430w  # 北纬30°05'28.867", 西经81°30'28.430"
      
      # 航路点2（佛罗里达州北部）
      position 30:10:07.914n 81:43:41.103w  # 北纬30°10'07.914", 西经81°43'41.103"
      
      # 航路点3（乔治亚州南部）
      position 30:23:14.716n 81:39:16.362w  # 北纬30°23'14.716", 西经81°39'16.362"
      
      # 航路点4（乔治亚州东南部）
      position 30:28:24.576n 81:19:55.787w  # 北纬30°28'24.576", 西经81°19'55.787"
      
      # 航路点5（南卡罗来纳州）
      position 30:30:07.754n 80:23:26.618w  # 北纬30°30'07.754", 西经80°23'26.618"
   end_route  # 结束路径定义

end_platform  # 轰炸机平台定义结束



### 车实体定义

platform car_1 CAR
   position 30:22:21.581n 81:44:17.259w
   side blue
   route
      position 30:22:21.581n 81:44:17.259w altitude 0.00 ft
         speed 50 mph
      position 30:47:42n 81:44:27w
   end_route
end_platform


### 坦克实体定义

platform tank_1 TANK
   position 30:10:08.999n 81:37:02.078w
   side blue
   heading 90 degrees
end_platform

platform tank_2 TANK
   position 30:01:57.10n 81:34:28.65w
   side blue
   heading 90 degrees
end_platform


### 卫星实体定义

platform satellite_1 SATELLITE
   position 29:43:50.597n 81:36:53.916w
   side blue
   altitude 700 km
   edit mover
      position 29:43:50.597n 81:36:53.916w
      altitude 700 km
      heading 90 deg
   end_mover
end_platform


### 防空导弹基地实体定义

platform sam_1 SINGLE_LARGE_SAM
   position 30:06:08.983n 81:34:42.446w
   side blue
   heading 90 degrees
end_platform
## 
            【/样板脚本】
        """
        )

        self.messages.append({"role": "system", "content": system_prompt})

    async def chat(self, prompt, role="user"):
        """与LLM进行交互"""
        self.messages.append({"role": role, "content": prompt})

        # TODO 第一次发送将tools发送给模型
        # 初始化 LLM API 调用
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=self.tools,
            tool_choice="auto",
            max_completion_tokens=8072
        )
        content = response.choices[0]
        # TODO 若 content.finish_reason == "tool_calls" 则调用了 MCP tools方法
        # TODO 发送第二次请求 将模型执行tools方法后的文本返回
        if content.finish_reason == "tool_calls":
            # 如果需要使用工具，解析工具调用
            tool_call = content.message.tool_calls[0]
            tool_name = tool_call.function.name  # tools方法名
            tool_args = json.loads(tool_call.function.arguments)  # tools方法需要的参数
            print(f"本次调用了{tool_name} 方法，方法参数包括：{tool_args}")

            # 执行工具方法
            result = await self.session.call_tool(tool_name, tool_args)
            # 将结果存入消息历史
            self.messages.append(content.message.model_dump())
            self.messages.append({
                "role": "tool",
                "content": result.content[0].text,
                "tool_call_id": tool_call.id,
            })

            # 将结果返回给大模型生成最终响应
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
            )
            print("----------------\n下列为结果：\n")
            print(response.choices[0].message.content)
            return response.choices[0].message.content
        # TODO 若本地调用不需要调用tool方法，直接返回结果
        return content.message.content

    # async def execute_tool(self, llm_response: str):
    #     """Process the LLM response and execute tools if needed.
    #     Args:
    #         llm_response: The response from the LLM.
    #     Returns:
    #         The result of tool execution or the original response.
    #     """
    #     import json
    #
    #     try:
    #
    #         tool_call = json.loads(llm_response.replace("```json\n", "").replace("```", ""))
    #
    #         print("tool" in tool_call and "arguments" in tool_call)
    #         if "tool" in tool_call and "arguments" in tool_call:
    #             # result = await self.session.call_tool(tool_name, tool_args)
    #             response = await self.session.list_tools()
    #             tools = response.tools
    #
    #             if any(tool.name == tool_call["tool"] for tool in tools):
    #                 try:
    #                     print("[提示]：正在执行函数")
    #                     result = await self.session.call_tool(
    #                         tool_call["tool"], tool_call["arguments"]
    #                     )
    #
    #                     if isinstance(result, dict) and "progress" in result:
    #                         progress = result["progress"]
    #                         total = result["total"]
    #                         percentage = (progress / total) * 100
    #                         print(f"Progress: {progress}/{total} ({percentage:.1f}%)")
    #                     # print(f"[执行结果]: {result}")
    #                     return f"Tool execution result: {result}"
    #                 except Exception as e:
    #                     error_msg = f"Error executing tool: {str(e)}"
    #                     print(error_msg)
    #                     return error_msg
    #
    #             return f"No server found with tool: {tool_call['tool']}"
    #         return llm_response
    #     except json.JSONDecodeError:
    #         return llm_response

    async def chat_loop(self):
        """运行交互式聊天循环"""
        print("MCP 客户端启动")
        print("输入 /bye 退出")

        while True:
            prompt = input(">>> ").strip()
            if prompt.lower() == '/bye':
                break

            llm_response = await self.chat(prompt)
            print(llm_response)
            # result = await self.execute_tool(llm_response)
            #
            # if result != llm_response:
            #     self.messages.append({"role": "assistant", "content": llm_response})
            #
            #     final_response = await self.chat(result, "system")
            #     print(final_response)
            #     self.messages.append(
            #         {"role": "assistant", "content": final_response}
            #     )
            # else:
            #     self.messages.append({"role": "assistant", "content": llm_response})


async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()

    await client.connect_to_server(sys.argv[1])
    await client.chat_loop()


if __name__ == "__main__":
    asyncio.run(main())
