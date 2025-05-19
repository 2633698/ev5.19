# ev_charging_project/app.py

from flask import Flask, render_template, request, jsonify, send_from_directory
import json
import os
import logging
from datetime import datetime, timedelta
import numpy as np
import time
import threading
import math
import random
import pickle
import traceback
import argparse
from types import SimpleNamespace # Use SimpleNamespace for the system object

# --- 关键导入 ---
# 检查这些导入是否能在运行时成功执行，需要正确的目录结构和 __init__.py 文件
try:
    from simulation.environment import ChargingEnvironment
    from simulation.scheduler import ChargingScheduler
    from simulation.metrics import calculate_rewards # <--- 确认导入 calculate_rewards
    # from training.train_model import train_and_save_model # 如果需要训练功能
except ImportError as e:
    # 如果在启动时就发生导入错误，应用可能无法正常运行
    logging.error(f"CRITICAL: Failed to import core modules: {e}", exc_info=True)
    # 定义一个函数占位符，防止后续调用时直接报错 NameError
    def calculate_rewards(state, config):
        logging.error("calculate_rewards function failed to import, returning default.")
        return {"user_satisfaction": 0,"operator_profit": 0,"grid_friendliness": 0,"total_reward": 0}
    # exit(1) # 或者根据需要选择退出

# --- Flask 应用初始化 ---
# 这里的 static_folder 和 template_folder 路径是相对于 app.py 的位置
# 确保 static/templates/index.html 存在
app = Flask(__name__, static_folder='static', template_folder='static/templates')

# --- 日志配置 ---
logging.basicConfig(
    level=logging.DEBUG,  # 确保是 DEBUG
    format='%(asctime)s - %(levelname)s - %(name)s - [%(funcName)s:%(lineno)d] - %(message)s', # 优化格式
    handlers=[
        logging.FileHandler("charging_system.log", mode='w'), # mode='w'
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("EVApp")
logger.info("Flask application instance created.")

# --- 全局变量 ---
simulation_running = False
simulation_thread = None
system = None # Will hold SimpleNamespace(env, scheduler, config)
current_state = { # 默认结构，防止后续访问出错
    "timestamp": datetime.now().isoformat(),
    "progress": 0,
    "metrics": {"user_satisfaction": 0,"operator_profit": 0,"grid_friendliness": 0,"total_reward": 0},
    "chargers": [],
    "users": [],
    "grid_status": {}
}
previous_states = {}
simulation_step_delay_ms = 100.0 # 默认速度 (ms/步)

# --- 配置加载 ---
def load_config():
    """Loads configuration from config.json, using defaults if necessary."""
    # (保持与上次提供版本一致)
    default_config = { # 确保默认配置是完整的
        "environment": {
            "grid_id": "DEFAULT001", "charger_count": 200, "user_count": 600,
            "simulation_days": 3, "time_step_minutes": 15, "station_count": 20,
            "chargers_per_station": 15, "region_count": 8, "charger_failure_rate": 0,
             "map_bounds": {"lat_min": 30, "lat_max": 30.05, "lng_min": 116, "lng_max": 116.05},
             "enable_uncoordinated_baseline": True,
             "min_charge_threshold_percent": 20.0,
             "force_charge_soc_threshold": 20.0,
             "default_charge_soc_threshold": 40.0,
             "charger_queue_capacity": 5
        },
        "grid": {
            "base_load": [32000, 28000, 24000, 22400, 21600, 24000, 36000, 48000, 60000, 64000, 65600, 67200, 64000, 60000, 56000, 52000, 56000, 60000, 68000, 72000, 64000, 56000, 48000, 40000],
            "solar_generation": [0, 0, 0, 0, 0, 0, 8000, 16000, 28800, 40000, 48000, 51200, 48000, 44800, 40000, 32000, 16000, 4800, 0, 0, 0, 0, 0, 0],
            "wind_generation": [19200, 22400, 24000, 20800, 16000, 19200, 24000, 27200, 20800, 16000, 19200, 20800, 24000, 27200, 25600, 22400, 25600, 28800, 32000, 28800, 25600, 24000, 20800, 22400],
            "peak_hours": [7, 8, 9, 10, 18, 19, 20, 21],
            "valley_hours": [0, 1, 2, 3, 4, 5],
            "normal_price": 0.85, "peak_price": 1.2, "valley_price": 0.4,
            "system_capacity_kw": 80000
        },
        "model": {"input_dim": 19, "hidden_dim": 128, "task_hidden_dim": 64, "model_path": "models/ev_charging_model.pth"},
        "scheduler": {
            "scheduling_algorithm": "rule_based",
            "optimization_weights": {"user_satisfaction": 0.35, "operator_profit": 0.35, "grid_friendliness": 0.35},
            "marl_config": {"action_space_size": 6, "discount_factor": 0.95, "exploration_rate": 0.1, "learning_rate": 0.01, "q_table_path": "models/marl_q_tables.pkl", "marl_candidate_max_dist_sq": 0.15**2, "marl_priority_w_soc": 0.5, "marl_priority_w_dist": 0.4, "marl_priority_w_urgency": 0.1},
             "use_trained_model": False,
             "use_multi_agent": True
        },
         "algorithms": {
             "rule_based": {
                 "max_queue": {"peak": 3, "valley": 12, "shoulder": 6},
                 "weight_adjustment": {"grid_boost_factor": 200, "valley_grid_reduction": 0.15},
                 "candidate_limit": 15,
                 "queue_penalty": 0.05
             },
             "uncoordinated": {
                 "soc_threshold": 50,
                 "max_queue": 4,
                 "score_weights": {"distance": 0.7, "queue_penalty_km": 5.0}
             }
        },
        "strategies": {
            "balanced": {"user_satisfaction": 0.33, "operator_profit": 0.33, "grid_friendliness": 0.34},
            "grid": {"user_satisfaction": 0.2, "operator_profit": 0.2, "grid_friendliness": 0.6},
            "profit": {"user_satisfaction": 0.2, "operator_profit": 0.6, "grid_friendliness": 0.2},
            "user": {"user_satisfaction": 0.6, "operator_profit": 0.2, "grid_friendliness": 0.2}
        },
        "visualization": {"output_dir": "output"}
    }
    config_path = 'config.json'
    loaded_config = {}
    import copy
    loaded_config = copy.deepcopy(default_config)

    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                def merge_dicts(d1, d2): # 简单的递归合并
                    for k, v in d2.items():
                        if isinstance(v, dict) and isinstance(d1.get(k), dict):
                            merge_dicts(d1[k], v)
                        else:
                            d1[k] = v
                merge_dicts(loaded_config, user_config)
            logger.info(f"Configuration loaded and merged from {config_path}")
        except json.JSONDecodeError:
            logger.error(f"Error decoding {config_path}. Using default configuration.", exc_info=True)
        except Exception as e:
            logger.error(f"Error loading {config_path}: {e}. Using default configuration.", exc_info=True)
    else:
        logger.warning(f"{config_path} not found. Using default configuration.")

    return loaded_config


# --- 系统初始化 ---
def initialize_system():
    """Initializes the simulation environment and scheduler."""
    global system, previous_states
    logger.debug("INITIALIZE_SYSTEM: Entered function.")
    previous_states = {}
    logger.info("Attempting to initialize system...")
    try:
        config = load_config() # 加载最新配置

        # --- 创建目录 ---
        output_dir = config.get("visualization", {}).get("output_dir", "output")
        models_dir = os.path.dirname(config.get("model", {}).get("model_path", "models/model.pth"))
        marl_q_path = config.get("scheduler", {}).get("marl_config", {}).get("q_table_path")
        marl_dir = os.path.dirname(marl_q_path) if marl_q_path else "models"

        os.makedirs(output_dir, exist_ok=True)
        if models_dir: os.makedirs(models_dir, exist_ok=True)
        if marl_dir: os.makedirs(marl_dir, exist_ok=True)
        logger.info("Ensured output/model directories exist.")
        # --- 结束创建目录 ---

        system_obj = SimpleNamespace()
        system_obj.config = config

        # 初始化 Environment 和 Scheduler
        logger.info("Initializing ChargingEnvironment...")
        system_obj.env = ChargingEnvironment(config)
        logger.info("ChargingEnvironment initialized.")

        logger.info(f"Initializing ChargingScheduler with algorithm: {config['scheduler'].get('scheduling_algorithm', 'rule_based')}")
        system_obj.scheduler = ChargingScheduler(config)
        logger.info("ChargingScheduler initialized.")

        # 加载 MARL Q-tables (如果适用)
        system_obj.scheduler.load_q_tables()

        logger.info(f"INITIALIZE_SYSTEM: Attempting to assign system_obj. env is {'present' if hasattr(system_obj, 'env') and system_obj.env else 'MISSING'}, scheduler is {'present' if hasattr(system_obj, 'scheduler') and system_obj.scheduler else 'MISSING'}")

        system = system_obj # 赋值给全局变量
        logger.info(f"INITIALIZE_SYSTEM: Successfully assigned system_obj to global system. REAL system should be active.")
        logger.info("System initialization successful.")
        return system

    except ImportError as e:
         logger.error(f"CRITICAL: Module import error during initialization: {e}. Check directory structure and __init__.py files.", exc_info=True)
         logger.warning("INITIALIZE_SYSTEM: FALLBACK to dummy system due to general Exception.")
         logger.warning("INITIALIZE_SYSTEM: FALLBACK to dummy system due to ImportError.")
         system = SimpleNamespace(config=load_config(), env=None, scheduler=None)
         return system
    except Exception as e:
        logger.error(f"CRITICAL: Error during system initialization: {e}", exc_info=True)
        minimal_system = SimpleNamespace()
        minimal_system.config = load_config()
        minimal_system.env = SimpleNamespace(
            chargers={}, users={}, grid_status={"grid_load_percentage": 0, "current_ev_load": 0, "renewable_ratio": 0, "current_price": 0.8},
            current_time = datetime.now(),
            get_current_state=lambda: {"timestamp": datetime.now().isoformat(), "users": [], "chargers": [], "grid_status": minimal_system.env.grid_status},
            step=lambda decisions: ({"user_satisfaction": 0, "operator_profit": 0, "grid_friendliness": 0, "total_reward": 0}, minimal_system.env.get_current_state(), False),
            reset=lambda: minimal_system.env.get_current_state()
        )
        minimal_system.scheduler = SimpleNamespace( make_scheduling_decision=lambda state: {}, learn=lambda s, a, r, ns: None, load_q_tables=lambda: None, save_q_tables=lambda: None, algorithm="fallback" )
        system = minimal_system
        return minimal_system

# --- 辅助函数：使用特定配置初始化 ---
def initialize_system_with_config(config_to_use):
     global system
     original_load_config = globals()['load_config']
     globals()['load_config'] = lambda: config_to_use
     try:
         system = initialize_system()
     finally:
         globals()['load_config'] = original_load_config
     return system

# --- 仿真运行函数 ---
def run_simulation(days, strategy="balanced", algorithm="rule_based"):
    """Main simulation loop thread function."""
    global current_state, simulation_running, system, previous_states, simulation_step_delay_ms
    logger.info(f"RUN_SIMULATION_THREAD: Entered. Days={days}, Strategy={strategy}, Algorithm={algorithm}")
    previous_states = {}
    logger.info(f"Starting simulation thread: days={days}, strategy={strategy}, algorithm={algorithm}")

    try:
        config = load_config() # Load base config
        # Update config based on runtime parameters
        config["scheduler"]["scheduling_algorithm"] = algorithm
        if algorithm in ["rule_based", "coordinated_mas"]:
            if strategy in config["strategies"]:
                config["scheduler"]["optimization_weights"] = config["strategies"][strategy]
                logger.info(f"Using strategy weights for '{strategy}': {config['strategies'][strategy]}")
            else:
                 logger.warning(f"Unknown strategy '{strategy}', using balanced weights.")
                 config["scheduler"]["optimization_weights"] = config.get("strategies", {}).get("balanced", {"user_satisfaction": 0.33, "operator_profit": 0.33, "grid_friendliness": 0.34})

        # Re-initialize system with the potentially modified config for this run
        logger.info("Initializing system for simulation run...")
        initialize_system_with_config(config)
        logger.info(f"RUN_SIMULATION_THREAD: System re-initialized for this run. system.env is {'present' if system and system.env else 'MISSING/DUMMY'}, system.scheduler is {'present' if system and system.scheduler else 'MISSING/DUMMY'}")
        if not system or not system.env or not system.scheduler or getattr(system.scheduler, 'algorithm', 'fallback') == 'fallback':
            logger.error("RUN_SIMULATION_THREAD: Critical system components missing after initialization. Aborting thread.")
            simulation_running = False
            return

        if not system or not system.env or not system.scheduler or getattr(system.scheduler, 'algorithm', 'fallback') == 'fallback':
             logger.error("System initialization failed. Aborting simulation run.")
             simulation_running = False
             return

        simulation_running = True
        logger.info(f"RUN_SIMULATION_THREAD: Global simulation_running flag is now True.")
        time_step = system.config.get('environment', {}).get('time_step_minutes', 15)
        total_steps = days * 24 * 60 // time_step
        current_step = 0
        metrics_history = []

        logger.info(f"Resetting environment for {total_steps} steps.")
        state = system.env.reset() # Initial state
        logger.info(f"RUN_SIMULATION_THREAD: Initial grid_status from env.reset(): {state.get('grid_status')}")
        previous_states['global_for_reward'] = state # Store initial state

        while current_step < total_steps and simulation_running:
            logger.debug(f"RUN_SIMULATION_THREAD: ----- Loop Start: Step {current_step}/{total_steps}. simulation_running is {simulation_running} -----")
            current_time_step_start = time.time()

            # --- Decision Making ---
            state_for_decision = system.env.get_current_state()
            previous_states['global_for_reward'] = state_for_decision # Store state before decision

            decisions = system.scheduler.make_scheduling_decision(state_for_decision)
            # ---> If MARL, store the raw actions if needed for learning <---
            # raw_marl_actions = system.scheduler.marl_system.last_raw_actions if system.scheduler.algorithm == "marl" else None

            # --- Environment Step ---
            rewards, next_state, done = system.env.step(decisions)

            # --- MARL Learning Step ---
            if system.scheduler.algorithm == "marl":
                 # TODO: Adjust the format of 'actions' passed to learn if needed
                 # It currently receives 'decisions' ({user_id: charger_id})
                 # It might need the raw {charger_id: action_index} (raw_marl_actions)
                 system.scheduler.learn(state_for_decision, decisions, rewards, next_state)

            # --- Record Metrics ---
            current_grid_status = next_state.get("grid_status", {})
            metrics_history.append({
                "timestamp": next_state.get("timestamp"),
                "rewards": rewards,
                "grid_load": current_grid_status.get("grid_load_percentage", 0),
                "ev_load": current_grid_status.get("current_ev_load", 0),
                "total_load": current_grid_status.get("current_total_load", 0),
                "renewable_ratio": current_grid_status.get("renewable_ratio", 0)
            })

            # --- Update Global State for UI ---
            current_step += 1
            current_progress = (current_step / total_steps) * 100
            current_state = {
                "timestamp": next_state.get("timestamp"),
                "progress": current_progress,
                "metrics": rewards,
                "chargers": next_state.get("chargers", []),
                "users": next_state.get("users", []),
                "grid_status": next_state.get("grid_status", {})
            }
            logger.debug(f"RUN_SIMULATION_THREAD: Global current_state.grid_status updated to: {current_state.get('grid_status')}")

            # --- Simulation Speed Control ---
            step_duration_actual = time.time() - current_time_step_start
            delay_needed = (simulation_step_delay_ms / 1000.0) - step_duration_actual
            if delay_needed > 0: time.sleep(delay_needed)

            if done:
                 logger.info("Simulation completed (reached end time).")
                 break

        # --- Simulation End ---
        logger.info(f"RUN_SIMULATION_THREAD: Exited simulation loop. simulation_running={simulation_running}, current_step={current_step}")
        logger.info(f"Simulation finished. Recorded {len(metrics_history)} steps.")
        if simulation_running: # Only update if not stopped externally
            final_state = system.env.get_current_state()
            final_rewards = calculate_rewards(final_state, system.config) # Use imported function
            current_state = {
                "timestamp": final_state.get("timestamp"),
                "progress": 100.0,
                "metrics": final_rewards,
                "chargers": final_state.get("chargers", []),
                "users": final_state.get("users", []),
                "grid_status": final_state.get("grid_status", {}),
                "metrics_history": metrics_history
            }

            # Save MARL Q-tables if applicable
            system.scheduler.save_q_tables()

            # Save final results
            result_dir = system.config.get("visualization", {}).get("output_dir", "output")
            result_filename = f"simulation_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{algorithm}_{strategy}.json"
            result_path = os.path.join(result_dir, result_filename)
            try:
                # Ensure metrics_history is included if it exists
                data_to_save = current_state.copy()
                if not metrics_history: data_to_save.pop('metrics_history', None)

                with open(result_path, 'w', encoding='utf-8') as f:
                    json.dump(data_to_save, f, indent=4, default=lambda x: int(x) if isinstance(x, np.integer) else float(x) if isinstance(x, np.floating) else str(x))
                logger.info(f"Simulation results saved to {result_path}")
            except Exception as e:
                logger.error(f"Error saving simulation results: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Simulation run failed critically: {e}", exc_info=True)
    finally:
        simulation_running = False # Ensure running flag is reset
        logger.info(f"RUN_SIMULATION_THREAD: simulation_running flag is now False. Thread terminated.")
        logger.info("Simulation thread terminated.")


# --- Flask Routes ---
@app.route('/')
def index():
    logger.info(f"Request received for root URL ('/')")
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index.html: {e}", exc_info=True)
        # 返回一个更友好的错误页面或消息
        return f"Internal Server Error: Template rendering failed. Check logs. Error: {e}", 500

# --- 其他 API 和页面路由 ---
# (与上次提供的版本一致，确保它们能正确处理 system 可能为 None 或 dummy 的情况)
@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    # (与上次提供的包含健壮合并逻辑的版本一致)
    try:
        updated_config = request.get_json()
        if not updated_config: raise ValueError("Received empty config data")
        logger.info(f"Received config update request...") # Avoid logging potentially large config
        config = load_config()
        def merge_dicts(d1, d2):
            for k, v in d2.items():
                if isinstance(v, dict) and isinstance(d1.get(k), dict): merge_dicts(d1[k], v)
                else: d1[k] = v
        merge_dicts(config, updated_config)
        # Add type validation/conversion here if needed
        with open('config.json', 'w', encoding='utf-8') as f: json.dump(config, f, indent=4)
        logger.info("Configuration saved to config.json")
        # Re-initialize the system with the new config *if not running*
        if not simulation_running:
             logger.info("Reloading system with updated configuration...")
             initialize_system_with_config(config)
             logger.info("System reloaded.")
        else:
             logger.warning("Simulation is running. Configuration will be applied on next start/reset.")

        return jsonify({"success": True, "config": config})
    except Exception as e:
        logger.error(f"Error updating config: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 400


@app.route('/api/simulation/start', methods=['POST'])
def start_simulation():
    global simulation_thread, simulation_running
    logger.info(f"API_START_SIM: Received start request. Current global simulation_running: {simulation_running}")

    if simulation_running:
        logger.warning("API_START_SIM: Simulation already running, ignoring request.")
        return jsonify({"status": "error", "message": "Simulation already running"})

    data = request.json
    days = data.get('days', 7)
    strategy = data.get('strategy', 'balanced')
    algorithm = data.get('algorithm', 'rule_based')
    valid_algorithms = ["rule_based", "coordinated_mas", "marl", "uncoordinated"]
    if algorithm not in valid_algorithms:
        algorithm = "rule_based"

    logger.info(f"API_START_SIM: Attempting to start simulation thread with days={days}, strategy={strategy}, algorithm={algorithm}")

    simulation_thread = threading.Thread(target=run_simulation, args=(days, strategy, algorithm))
    simulation_thread.daemon = True
    simulation_thread.start()
    logger.info(f"API_START_SIM: Simulation thread object created and start() called.")

    # 关键的修改在这里：
    time.sleep(0.2) 
    logger.info(f"API_START_SIM: After 0.2s sleep, global simulation_running is: {simulation_running}")
    if simulation_running: 
        logger.info("API_START_SIM: Responding 'success' to client as simulation_running is True.")
        return jsonify({"status": "success", "message": "Simulation started"})
    else:
        logger.error("API_START_SIM: Simulation thread might not have set 'simulation_running' to True. Responding 'error'. Check run_simulation logs for initialization issues.")
        return jsonify({"status": "error", "message": "Simulation failed to confirm running state. Check backend logs."})

@app.route('/api/simulation/stop', methods=['POST'])
def stop_simulation():
    # (与上次提供版本一致)
    global simulation_running
    if not simulation_running: return jsonify({"status": "error", "message": "No simulation running"})
    logger.info("Received request to stop simulation.")
    simulation_running = False # Signal the thread to stop
    return jsonify({"status": "success", "message": "Simulation stop signal sent"})

@app.route('/api/simulation/status', methods=['GET'])

def get_simulation_status():
    # (与上次提供版本一致)
    global current_state, simulation_running
    state_to_send = { # Provide default structure
         "timestamp": datetime.now().isoformat(), "progress": 0, "metrics": {},
         "grid_status": {}, "chargers": [], "users": []
    }
    state_to_send.update(current_state) # Overwrite with actual data if available
    # Ensure lists, not dicts for chargers/users
    if isinstance(state_to_send.get("chargers"), dict): state_to_send["chargers"] = list(state_to_send["chargers"].values())
    if isinstance(state_to_send.get("users"), dict): state_to_send["users"] = list(state_to_send["users"].values())
    return jsonify({"running": simulation_running, "state": state_to_send})
# --- 其他 /api/... 路由保持不变 ---
# ... /api/chargers, /api/users, /api/grid, /output/, /api/simulation/results,
# ... /api/simulation/result/<filename>, /api/user/recommendations,
# ... /api/operator/statistics, /api/grid/statistics, /api/simulation/speed,
# ... /api/system_state, /api/debug/marl_test

# --- /admin, /user, /operator, /grid 页面路由 ---
# (保持不变，确保对应的模板文件在 static/templates/ 下)
@app.route('/admin')
def admin_dashboard(): return render_template('admin.html') # 假设有 admin.html
@app.route('/user')
def user_dashboard(): return render_template('user.html') # 假设有 user.html
@app.route('/operator')
def operator_dashboard(): return render_template('operator.html') # 假设有 operator.html
@app.route('/grid')
def grid_dashboard(): return render_template('grid.html') # 假设有 grid.html

# --- 调试状态函数 ---
def debug_marl_state():
     # (保持不变)
     test_time = datetime.now().isoformat()
     users = [{"user_id": f"TEST_USER_{i+1}", "soc": 20.0 + i*2, "status": "traveling", "current_position": {"lat": 30.75 + random.uniform(-0.05, 0.05), "lng": 114.25 + random.uniform(-0.05, 0.05)}} for i in range(10)]
     chargers = [{"charger_id": f"TEST_CHARGER_{i+1}", "status": "available", "position": {"lat": 30.75 + random.uniform(-0.02, 0.02), "lng": 114.25 + random.uniform(-0.02, 0.02)}, "type": "fast" if i%2==0 else "slow", "queue": []} for i in range(5)]
     grid_status = {"grid_load_percentage": 50, "current_ev_load": 10, "renewable_ratio": 40, "current_price": 0.8, "peak_hours": [7, 8, 9, 10, 18, 19, 20, 21], "valley_hours": [0, 1, 2, 3, 4, 5]}
     return {"timestamp": test_time, "users": users, "chargers": chargers, "grid_status": grid_status}

# --- 信号处理 ---
def signal_handler(sig, frame):
     # (保持不变)
     global system
     logger.info('Shutdown signal received. Saving Q-tables if MARL is active...')
     if system and hasattr(system, 'scheduler'):
         system.scheduler.save_q_tables()
     else: logger.warning("System or scheduler not initialized, cannot save Q-tables.")
     logger.info("Exiting.")
     exit(0)

# --- Main Execution ---
if __name__ == '__main__':
    # (保持与上次提供版本一致的启动检查和命令行参数处理)
    logger.info("="*50); logger.info("Starting EV Charging Simulation System")
    logger.info(f"Current Working Directory: {os.getcwd()}")
    logger.info("Checking essential directories and files...")
    static_dir_exists = os.path.isdir("static"); templates_dir_exists = os.path.isdir("static/templates")
    index_html_exists = os.path.exists("static/templates/index.html")
    sim_init_exists = os.path.exists("simulation/__init__.py"); algo_init_exists = os.path.exists("algorithms/__init__.py")
    logger.info(f"  'static/' exists: {static_dir_exists}"); logger.info(f"  'static/templates/' exists: {templates_dir_exists}")
    logger.info(f"  'static/templates/index.html' exists: {index_html_exists}")
    logger.info(f"  'simulation/__init__.py' exists: {sim_init_exists}"); logger.info(f"  'algorithms/__init__.py' exists: {algo_init_exists}")
    logger.info("="*50)
    if not static_dir_exists or not templates_dir_exists or not index_html_exists: logger.error("ERROR: Frontend directories/files not found! Check structure.")
    if not sim_init_exists or not algo_init_exists: logger.error("ERROR: Required '__init__.py' missing! Imports may fail.")

    parser = argparse.ArgumentParser(description='EV Charging Simulation System')
    parser.add_argument('--cli', action='store_true', help='Run in CLI mode')
    parser.add_argument('--days', type=int, default=None, help='Simulation days (overrides config)')
    parser.add_argument('--strategy', type=str, default=None, choices=['balanced', 'user', 'grid', 'profit'], help='Optimization strategy')
    parser.add_argument('--algorithm', type=str, default=None, choices=['rule_based', 'coordinated_mas', 'marl', 'uncoordinated'], help='Scheduling algorithm')
    parser.add_argument('--output', type=str, help='Output file path for CLI results')
    args = parser.parse_args()

    logger.info("Initializing system on startup...")
    system = initialize_system() # 初始化系统
    if system and system.env and system.scheduler and getattr(system.scheduler, 'algorithm', 'fallback') != 'fallback':
        logger.info("MAIN: System initialized successfully from initialize_system().")
    else:
        logger.error("MAIN: System initialization FAILED or resulted in a dummy system. Check logs from initialize_system.")

    if args.cli:
        # (CLI 模式逻辑保持不变)
        # ... [加载配置, 运行仿真, 保存结果, 打印摘要] ...
         config = load_config()
         sim_days = args.days if args.days is not None else config.get('environment', {}).get('simulation_days', 7)
         sim_strategy = args.strategy if args.strategy is not None else 'balanced'
         sim_algorithm = args.algorithm if args.algorithm is not None else config.get('scheduler', {}).get('scheduling_algorithm', 'rule_based')
         logger.info(f"Running in CLI mode: Days={sim_days}, Strategy={sim_strategy}, Algorithm={sim_algorithm}")
         if not system or not system.env or not system.scheduler or getattr(system.scheduler, 'algorithm', 'fallback') == 'fallback':
             logger.error("System initialization failed. Cannot run CLI simulation.")
         else:
             run_simulation(sim_days, sim_strategy, sim_algorithm)
             if args.output: # 保存结果
                 output_dir = os.path.dirname(args.output);
                 if output_dir: os.makedirs(output_dir, exist_ok=True)
                 try:
                     with open(args.output, 'w', encoding='utf-8') as f:
                         json.dump(current_state, f, indent=4, default=lambda x: int(x) if isinstance(x, np.integer) else float(x) if isinstance(x, np.floating) else str(x))
                     logger.info(f"Simulation results saved to {args.output}")
                 except Exception as e: logger.error(f"Error saving CLI results: {e}", exc_info=True)
             # 打印摘要
             print("\nCLI Simulation finished. Final Metrics:")
             fm = current_state.get('metrics', {})
             print(f"  User Satisfaction: {fm.get('user_satisfaction', 0):.4f}")
             print(f"  Operator Profit:   {fm.get('operator_profit', 0):.4f}")
             print(f"  Grid Friendliness: {fm.get('grid_friendliness', 0):.4f}")
             print(f"  Total Reward:      {fm.get('total_reward', 0):.4f}")
    else:
        # Web Mode
        logger.info("Starting Flask development server...")
        if not system or not system.env or not system.scheduler or getattr(system.scheduler, 'algorithm', 'fallback') == 'fallback':
            logger.error("System initialization failed! Web server starting with limited functionality.")
        app.run(debug=True, port=5000, use_reloader=False)

# Optional: Signal handler
# import signal
# signal.signal(signal.SIGINT, signal_handler)
# signal.signal(signal.SIGTERM, signal_handler)