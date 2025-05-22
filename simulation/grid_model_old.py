# ev_charging_project/simulation/grid_model.py
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class GridModel:
    def __init__(self, config):
        """初始化电网模型"""
        # 安全获取配置，提供默认值
        self.config = config.get('grid', {})
        self.environment_config = config.get('environment', {})
        self.grid_status = {}
        self.reset() # 初始化状态

    def reset(self):
        """重置电网状态到初始值"""
        logger.info("Resetting GridModel status...")
        # 从配置读取，提供更高默认值
        base_load_profile = self.config.get("base_load", [
            16000, 14000, 12000, 11000, 10000, 11000, 18000, 24000, 30000, 32000, 32800, 33600,
            32000, 30000, 28000, 26000, 28000, 30000, 34000, 36000, 32000, 28000, 24000, 20000
        ])
        peak_hours = self.config.get("peak_hours", [7, 8, 9, 10, 18, 19, 20, 21])
        valley_hours = self.config.get("valley_hours", [0, 1, 2, 3, 4, 5])
        solar_generation = self.config.get("solar_generation", [0]*24)
        wind_generation = self.config.get("wind_generation", [1000]*24)
        normal_price = self.config.get("normal_price", 0.85)
        peak_price = self.config.get("peak_price", 1.2)
        valley_price = self.config.get("valley_price", 0.4)
        system_capacity = self.config.get("system_capacity_kw", 60000) # 系统容量

        # 验证 base_load_profile
        if not isinstance(base_load_profile, list) or len(base_load_profile) != 24:
             logger.warning(f"Invalid base_load in config. Using default.")
             base_load_profile = [16000] * 24 # Fallback default

        initial_hour = 0
        initial_base_load = base_load_profile[initial_hour]
        initial_solar = solar_generation[initial_hour] if len(solar_generation) == 24 else 0
        initial_wind = wind_generation[initial_hour] if len(wind_generation) == 24 else 0
        initial_ev_load = 0
        initial_total_load = initial_base_load + initial_ev_load

        self.grid_status = {
            "base_load_profile": base_load_profile,
            "solar_generation_profile": solar_generation,
            "wind_generation_profile": wind_generation,
            "peak_hours": peak_hours,
            "valley_hours": valley_hours,
            "normal_price": normal_price,
            "peak_price": peak_price,
            "valley_price": valley_price,
            "system_capacity": system_capacity,
            # --- 当前状态值 ---
            "current_base_load": initial_base_load,
            "current_solar_gen": initial_solar,
            "current_wind_gen": initial_wind,
            "current_ev_load": initial_ev_load,
            "current_total_load": initial_total_load,
            "current_price": self._get_current_price(initial_hour),
            "grid_load_percentage": (initial_total_load / system_capacity) * 100 if system_capacity > 0 else 0,
            "renewable_ratio": ((initial_solar + initial_wind) / initial_total_load * 100) if initial_total_load > 0 else 0
        }
        logger.info("GridModel reset complete.")

    def update_step(self, current_time, ev_load):
        """更新电网在一个时间步的状态"""
        hour = current_time.hour
        if not (0 <= hour < 24):
             logger.error(f"Invalid hour ({hour}) for grid update. Using hour 0.")
             hour = 0

        # 安全地访问 profile 数据
        base_load = self.grid_status.get('base_load_profile', [16000]*24)[hour]
        solar_gen = self.grid_status.get('solar_generation_profile', [0]*24)[hour]
        wind_gen = self.grid_status.get('wind_generation_profile', [1000]*24)[hour]

        # 计算总负载和百分比
        total_load = base_load + ev_load
        system_capacity = self.grid_status.get("system_capacity", 60000)
        grid_load_percentage = (total_load / system_capacity) * 100 if system_capacity > 0 else 0

        # 计算可再生能源比例
        total_renewable = solar_gen + wind_gen
        renewable_ratio = (total_renewable / total_load * 100) if total_load > 0 else 0

        # 更新电价
        current_price = self._get_current_price(hour)

        # 更新 grid_status 字典
        self.grid_status.update({
            "current_base_load": base_load,
            "current_solar_gen": solar_gen,
            "current_wind_gen": wind_gen,
            "current_ev_load": ev_load,
            "current_total_load": total_load,
            "current_price": current_price,
            "grid_load_percentage": grid_load_percentage,
            "renewable_ratio": renewable_ratio
        })
        # logger.debug(f"Grid updated @ {current_time}: TotalLoad={total_load:.1f}kW ({grid_load_percentage:.1f}%), EVLoad={ev_load:.1f}kW, Renew%={renewable_ratio:.1f}%")

    def _get_current_price(self, hour):
        """根据小时获取电价"""
        if hour in self.grid_status.get("peak_hours", []):
            return self.grid_status.get("peak_price", 1.2)
        elif hour in self.grid_status.get("valley_hours", []):
            return self.grid_status.get("valley_price", 0.4)
        else:
            return self.grid_status.get("normal_price", 0.85)

    def get_status(self):
        """返回当前的电网状态字典"""
        return self.grid_status.copy()