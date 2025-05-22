import logging
import copy # For deep copying config
from PySide6.QtCore import QObject, Signal, QThread, Slot
from gui.simulation_thread import SimulationWorker

logger = logging.getLogger(__name__)

class SimulationConnector(QObject):
    connector_step_updated = Signal(int)
    connector_kpis_updated = Signal(dict)
    connector_grid_status_updated = Signal(dict)
    connector_status_update = Signal(str)
    connector_simulation_finished = Signal()
    connector_error_occurred = Signal(str)
    # Signal to notify that the internal current_config has changed (optional, for debugging or advanced UI)
    # internal_config_changed_signal = Signal(dict) 

    def __init__(self, initial_config): # Renamed config to initial_config for clarity
        super().__init__()
        self.initial_config = initial_config # Store the original config loaded at startup
        self.current_config = copy.deepcopy(initial_config) # Working copy for modifications
        self.thread = None
        self.worker = None
        self.is_running = False
        self.is_paused = False
        logger.info("SimulationConnector initialized with configuration.")
        self.print_config_summary(self.current_config, "Initial current_config") # Log initial state of current_config

    def print_config_summary(self, config_to_print, context_message="Config"):
        if config_to_print:
            env_config = config_to_print.get('environment', {})
            scheduler_config = config_to_print.get('scheduler', {})
            logger.info(f"{context_message} Summary: Grid ID: {env_config.get('grid_id')}, Sim Days: {env_config.get('simulation_days')}")
            logger.info(f"Scheduler Algorithm: {scheduler_config.get('scheduling_algorithm')}, MARL: {scheduler_config.get('use_multi_agent')}")
            logger.info(f"Optimization Weights: {scheduler_config.get('optimization_weights')}")
        else:
            logger.warning(f"{context_message}: No configuration loaded.")

    def start_simulation(self):
        if self.is_running and not self.is_paused:
            logger.warning("SimulationConnector: Simulation is already running.")
            self.connector_status_update.emit("仿真已在运行 (Simulation already running)")
            return
        
        if self.is_paused:
            self.resume_simulation()
            return

        logger.info("SimulationConnector: Start simulation triggered using current_config.")
        self.print_config_summary(self.current_config, "Starting simulation with current_config")
        self.connector_status_update.emit("正在启动仿真... (Starting simulation...)")

        self.thread = QThread()
        self.worker = SimulationWorker()
        self.worker.moveToThread(self.thread)

        # Connect worker signals
        self.worker.step_completed.connect(self.on_step_completed)
        self.worker.kpis_updated.connect(self.on_kpis_updated)
        self.worker.grid_status_updated.connect(self.on_grid_status_updated)
        self.worker.simulation_finished.connect(self.on_simulation_finished)
        self.worker.error_occurred.connect(self.on_simulation_error)
        self.worker.status_update.connect(self.on_worker_status_update)

        # Pass the current_config to the worker
        self.thread.started.connect(lambda: self.worker.run_simulation(self.current_config))
        self.thread.finished.connect(self.on_thread_finished)

        self.thread.start()
        self.is_running = True
        self.is_paused = False
        logger.info("SimulationConnector: Simulation thread started.")
        self.connector_status_update.emit("仿真线程已启动 (Simulation thread started)")

    def pause_simulation(self):
        if not self.is_running or self.is_paused:
            logger.warning("SimulationConnector: Simulation not running or already paused.")
            self.connector_status_update.emit("仿真未运行或已暂停 (Not running or already paused)")
            return
        if self.worker:
            self.worker.pause()
            self.is_paused = True
            logger.info("SimulationConnector: Pause simulation requested.")
            self.connector_status_update.emit("仿真已暂停 (Simulation Paused)")

    def resume_simulation(self):
        if not self.is_running or not self.is_paused:
            logger.warning("SimulationConnector: Simulation not running or not paused.")
            self.connector_status_update.emit("仿真未运行或未暂停 (Not running or not paused)")
            return
        if self.worker:
            self.worker.resume()
            self.is_paused = False
            logger.info("SimulationConnector: Resume simulation requested.")
            self.connector_status_update.emit("仿真已恢复 (Simulation Resumed)")

    def reset_simulation(self):
        logger.info("SimulationConnector: Reset simulation triggered.")
        if self.worker:
            self.worker.stop()

        if self.thread and self.thread.isRunning():
            logger.info("SimulationConnector: Waiting for simulation thread to quit...")
            self.thread.quit()
            if not self.thread.wait(5000):
                 logger.warning("SimulationConnector: Simulation thread did not quit gracefully. Terminating.")
                 self.thread.terminate()
                 self.thread.wait()
        
        self._cleanup_thread_and_worker()
        self.is_running = False
        self.is_paused = False
        logger.info("SimulationConnector: Simulation reset complete. Current config remains as last set by GUI.")
        self.print_config_summary(self.current_config, "Config after reset (should be last GUI-set values)")
        self.connector_status_update.emit("仿真已重置 (Simulation Reset)")
        self.connector_step_updated.emit(0) 
        self.connector_kpis_updated.emit({})
        self.connector_grid_status_updated.emit({})

    @Slot(str, object)
    def update_simulation_parameter(self, param_name, param_value):
        logger.info(f"SimulationConnector: Attempting to update parameter '{param_name}' to '{param_value}'.")
        # Ensure scheduler config exists
        if 'scheduler' not in self.current_config:
            self.current_config['scheduler'] = {}
        
        if param_name == "strategy_mode":
            # Fetch the weights for the selected strategy from the initial_config
            strategy_weights = self.initial_config.get('strategies', {}).get(param_value)
            if strategy_weights:
                if 'optimization_weights' not in self.current_config['scheduler']:
                    self.current_config['scheduler']['optimization_weights'] = {}
                self.current_config['scheduler']['optimization_weights'] = copy.deepcopy(strategy_weights)
                logger.info(f"Updated optimization_weights for strategy '{param_value}': {self.current_config['scheduler']['optimization_weights']}")
            else:
                logger.warning(f"Strategy '{param_value}' not found in initial_config. Weights not updated.")
        elif param_name == "scheduling_algorithm":
            self.current_config['scheduler']['scheduling_algorithm'] = param_value
            logger.info(f"Updated scheduling_algorithm to: {param_value}")
            # Potentially update use_multi_agent based on algorithm
            if param_value == "coordinated_mas" or param_value == "marl":
                self.current_config['scheduler']['use_multi_agent'] = True
            else:
                self.current_config['scheduler']['use_multi_agent'] = False
            logger.info(f"Updated use_multi_agent to: {self.current_config['scheduler']['use_multi_agent']}")
        else:
            # Generic parameter update (e.g., if directly setting a weight in the future)
            # This needs a more robust way to set nested dict values if param_name can be "scheduler.some_key"
            keys = param_name.split('.')
            d = self.current_config
            for key in keys[:-1]:
                d = d.setdefault(key, {})
            d[keys[-1]] = param_value
            logger.info(f"Updated generic parameter '{param_name}' to: {param_value}")
        
        self.print_config_summary(self.current_config, "Config after update_simulation_parameter")
        # self.internal_config_changed_signal.emit(self.current_config) # Optional: if other parts need to know


    def on_step_completed(self, current_step):
        self.connector_step_updated.emit(current_step)

    def on_kpis_updated(self, kpi_data):
        self.connector_kpis_updated.emit(kpi_data)
        
    def on_grid_status_updated(self, grid_data):
        self.connector_grid_status_updated.emit(grid_data)

    def on_simulation_finished(self):
        logger.info("SimulationConnector: Simulation finished by worker.")
        self.connector_status_update.emit("仿真正常结束 (Simulation Finished)")
        self.is_running = False
        self.is_paused = False
        self._cleanup_thread_and_worker()
        self.connector_simulation_finished.emit()

    def on_simulation_error(self, error_message):
        logger.error(f"SimulationConnector: Simulation error reported by worker: {error_message}")
        self.connector_status_update.emit(f"仿真错误: {error_message} (Simulation Error)")
        self.is_running = False
        self.is_paused = False
        self._cleanup_thread_and_worker()
        self.connector_error_occurred.emit(error_message)

    def on_worker_status_update(self, status_message):
        logger.info(f"SimulationConnector (from Worker): {status_message}")
        self.connector_status_update.emit(status_message)

    def on_thread_finished(self):
        logger.info("SimulationConnector: QThread finished.")
        if self.thread:
            self.thread.deleteLater()
        if self.worker:
            self.worker.deleteLater()
        
        if self.is_running: # Unexpected finish
            self.is_running = False
            self.is_paused = False
            self.connector_status_update.emit("仿真线程意外终止 (Thread terminated unexpectedly)")
        
        self.worker = None
        self.thread = None

    def _cleanup_thread_and_worker(self):
        logger.debug("SimulationConnector: Cleaning up thread and worker...")
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        if self.thread:
            if not self.thread.isFinished():
                self.thread.quit()
                self.thread.wait(1000)
            self.thread.deleteLater()
            self.thread = None
        logger.debug("SimulationConnector: Thread and worker cleanup done.")

    def get_status(self):
        logger.info("SimulationConnector: Get status triggered (provides static snapshot).")
        state = "Running" if self.is_running and not self.is_paused else \
                "Paused" if self.is_paused else \
                "Not Started/Finished"
        return {
            "simulation_state": state
        }

if __name__ == '__main__':
    from PySide6.QtCore import QCoreApplication, QTimer
    import sys

    logging.basicConfig(level=logging.DEBUG)
    app = QCoreApplication(sys.argv)
    
    mock_config = {
        "environment": {"grid_id": "TestGrid001", "simulation_days": 1, "time_step_minutes": 30},
        "scheduler": {"scheduling_algorithm": "rule_based", "use_multi_agent": False}
    }
    connector = SimulationConnector(config=mock_config)
    
    def handle_step(step): logger.info(f"TEST_APP: Step {step}")
    def handle_kpis(kpis): logger.info(f"TEST_APP: KPIs {kpis}")
    def handle_grid_status(grid_data): logger.info(f"TEST_APP: Grid Status {grid_data.get('current_price', 'N/A')}") # Example
    def handle_finish(): logger.info("TEST_APP: Finished"); QCoreApplication.quit()
    def handle_error(err): logger.error(f"TEST_APP: Error: {err}"); QCoreApplication.quit()
    def handle_status(msg): logger.info(f"TEST_APP: Status: {msg}")

    connector.connector_step_updated.connect(handle_step)
    connector.connector_kpis_updated.connect(handle_kpis)
    connector.connector_grid_status_updated.connect(handle_grid_status) # Connect new grid status signal
    connector.connector_simulation_finished.connect(handle_finish)
    connector.connector_error_occurred.connect(handle_error)
    connector.connector_status_update.connect(handle_status)

    connector.print_config_summary()
    connector.start_simulation()
    
    sys.exit(app.exec())
