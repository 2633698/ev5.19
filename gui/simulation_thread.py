import time
import logging
import numpy as np # For mock simulation if needed
from PySide6.QtCore import QObject, Signal, QCoreApplication

try:
    from simulation.environment import ChargingEnvironment
    from simulation.scheduler import ChargingScheduler
    REAL_SIM_COMPONENTS_AVAILABLE = True
    logger = logging.getLogger(__name__)
    logger.info("SimulationWorker: Successfully imported ChargingEnvironment and ChargingScheduler.")
except ImportError as e:
    REAL_SIM_COMPONENTS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.error(f"SimulationWorker: Failed to import core simulation components: {e}. Simulation will be a mock.", exc_info=True)
    ChargingEnvironment = None
    ChargingScheduler = None


class SimulationWorker(QObject):
    step_completed = Signal(int)
    kpis_updated = Signal(dict)
    grid_status_updated = Signal(dict) # New signal for detailed grid status
    simulation_finished = Signal()
    error_occurred = Signal(str)
    status_update = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pause_requested = False
        self._stop_requested = False
        self.env = None
        self.scheduler = None
        # self.mas_system = None # Not directly managed if scheduler handles it

    def run_simulation(self, config):
        logger.info("SimulationWorker: Starting simulation run...")
        self.status_update.emit("仿真初始化中... (Simulation Initializing...)")
        self._stop_requested = False
        self._pause_requested = False

        try:
            if not REAL_SIM_COMPONENTS_AVAILABLE or ChargingEnvironment is None or ChargingScheduler is None:
                logger.error("SimulationWorker: Cannot run real simulation, components missing. Falling back to MOCK.")
                # Fallback to mock simulation if real components are not available
                self._run_mock_simulation(config)
                return

            logger.info("SimulationWorker: Initializing REAL simulation environment and scheduler...")
            self.env = ChargingEnvironment(config)
            self.scheduler = ChargingScheduler(config) # Scheduler might init MAS internally
            
            # If coordinator weights need to be set based on strategy from config:
            # This assumes scheduler.mas_system.coordinator structure if use_multi_agent is True
            if self.scheduler.use_multi_agent and hasattr(self.scheduler, 'mas_system') and self.scheduler.mas_system:
                strategy_name = config.get('scheduler', {}).get('active_strategy', 'balanced') # Assuming active_strategy might be set
                strategy_weights = config.get('strategies', {}).get(strategy_name, 
                                                                     config.get('scheduler',{}).get('optimization_weights'))
                if strategy_weights and hasattr(self.scheduler.mas_system, 'coordinator') and \
                   hasattr(self.scheduler.mas_system.coordinator, 'set_weights'):
                    self.scheduler.mas_system.coordinator.set_weights(strategy_weights)
                    logger.info(f"SimulationWorker: Coordinator weights set for strategy '{strategy_name}'.")

            env_config = config.get('environment', {})
            simulation_days = env_config.get('simulation_days', 1)
            time_step_minutes = env_config.get('time_step_minutes', 15)
            
            if time_step_minutes <= 0:
                self.error_occurred.emit("time_step_minutes must be positive.")
                return

            total_steps = simulation_days * 24 * (60 // time_step_minutes)
            logger.info(f"SimulationWorker: Total simulation steps: {total_steps}")
            self.status_update.emit(f"总步数: {total_steps} (Total Steps: {total_steps})")

            current_sim_state = self.env.reset() # Initial state from environment

            for current_step in range(total_steps):
                if self._stop_requested:
                    logger.info("SimulationWorker: Stop requested. Terminating simulation.")
                    self.status_update.emit("仿真已停止 (Simulation Stopped)")
                    break

                while self._pause_requested:
                    if self._stop_requested: break
                    time.sleep(0.1) 
                if self._stop_requested: break

                # --- Actual Simulation Step ---
                # 1. Get decisions from scheduler (which uses MAS if configured)
                decisions = self.scheduler.make_scheduling_decision(current_sim_state)
                
                # 2. Apply decisions to environment and get new state, rewards (KPIs)
                # Rewards dict IS the KPIs dict: {'user_satisfaction': ..., 'operator_profit': ..., ...}
                rewards, next_sim_state, done = self.env.step(decisions)
                
                # 3. MARL learning step (if applicable)
                if self.scheduler.algorithm == "marl": # Check if scheduler is MARL
                    self.scheduler.learn(current_sim_state, decisions, rewards, next_sim_state)

                current_sim_state = next_sim_state # Update state for next iteration
                
                # 4. Get detailed grid status
                grid_status_data = {}
                if hasattr(self.env, 'grid_model') and self.env.grid_model:
                    grid_status_data = self.env.grid_model.get_status()
                else:
                    logger.warning("SimulationWorker: env.grid_model not available to fetch grid status.")

                # Emit signals
                self.step_completed.emit(current_step + 1)
                self.kpis_updated.emit(rewards) 
                self.grid_status_updated.emit(grid_status_data) # Emit detailed grid status

                if done:
                    logger.info("SimulationWorker: Environment indicated simulation is done.")
                    break

            if not self._stop_requested:
                logger.info("SimulationWorker: Simulation run completed.")
                self.status_update.emit("仿真完成 (Simulation Completed)")
            
            if self.scheduler and hasattr(self.scheduler, 'save_q_tables') and self.scheduler.algorithm == "marl":
                self.scheduler.save_q_tables()
                logger.info("SimulationWorker: MARL Q-tables saved.")

            self.simulation_finished.emit()

        except Exception as e:
            logger.error(f"SimulationWorker: Error during REAL simulation: {e}", exc_info=True)
            self.error_occurred.emit(f"Real Sim Error: {str(e)}")
        finally:
            self.env = None
            self.scheduler = None
            logger.info("SimulationWorker: Real simulation run method finished and resources cleaned up.")

    def _run_mock_simulation(self, config):
        logger.info("SimulationWorker: Running MOCK simulation loop.")
        env_config = config.get('environment', {})
        simulation_days = env_config.get('simulation_days', 1)
        time_step_minutes = env_config.get('time_step_minutes', 15)
        if time_step_minutes <= 0: time_step_minutes = 15
        total_steps = simulation_days * 24 * (60 // time_step_minutes)
        self.status_update.emit(f"模拟总步数: {total_steps} (Mock Total Steps: {total_steps})")
        
        num_regions_mock = env_config.get('region_count', 8) # Use region_count for mock
        mock_region_ids = [f"region_{i}" for i in range(num_regions_mock)]

        for current_step in range(total_steps):
            if self._stop_requested: break
            while self._pause_requested:
                if self._stop_requested: break
                time.sleep(0.1)
            if self._stop_requested: break
            
            time.sleep(0.05)
            self.step_completed.emit(current_step + 1)
            
            mock_kpis = {
                'user_satisfaction': np.random.rand() * 0.3 + 0.5,
                'operator_profit': np.random.rand() * 50 + 100,
                'grid_friendliness': np.random.rand() * 0.4 + 0.6,
                'total_reward': np.random.rand() * 100 + 150
            }
            self.kpis_updated.emit(mock_kpis)

            # Mock grid status data
            mock_grid_status = {
                'current_base_load_regional': {rid: np.random.uniform(50,150) for rid in mock_region_ids},
                'current_ev_load_regional': {rid: np.random.uniform(5,50) for rid in mock_region_ids},
                'current_total_load_regional': {rid: np.random.uniform(60,200) for rid in mock_region_ids},
                'grid_load_percentage_regional': {rid: np.random.uniform(30,90) for rid in mock_region_ids},
                'current_solar_gen_regional': {rid: np.random.uniform(0,80) for rid in mock_region_ids},
                'current_wind_gen_regional': {rid: np.random.uniform(0,70) for rid in mock_region_ids},
                'renewable_ratio_regional': {rid: np.random.uniform(10,60) for rid in mock_region_ids},
                'system_capacity_regional': {rid: 200 + np.random.uniform(-20,20) for rid in mock_region_ids}, # Example base capacity
                'current_price': 0.85 + np.random.uniform(-0.2, 0.2) # Global price
            }
            self.grid_status_updated.emit(mock_grid_status)
        
        if not self._stop_requested: self.status_update.emit("模拟仿真完成 (Mock Simulation Completed)")
        self.simulation_finished.emit()
        logger.info("SimulationWorker: Mock simulation run method finished.")

    def pause(self):
        logger.info("SimulationWorker: Pause requested.")
        self.status_update.emit("请求暂停 (Pause Requested)")
        self._pause_requested = True

    def resume(self):
        logger.info("SimulationWorker: Resume requested.")
        self.status_update.emit("请求继续 (Resume Requested)")
        self._pause_requested = False

    def stop(self):
        logger.info("SimulationWorker: Stop requested.")
        self.status_update.emit("请求停止 (Stop Requested)")
        self._stop_requested = True
        self._pause_requested = False

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logger.info("SimulationWorker standalone test (conceptual - requires Qt event loop for full test).")
    # Proper testing involves QThread as done in SimulationConnector.
    # worker = SimulationWorker() # This would log component import status
    # config_example = {"environment": {"simulation_days": 1, "time_step_minutes": 60}}
    # worker.run_simulation(config_example) # Direct call would block.
