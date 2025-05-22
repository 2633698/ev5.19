import json 
import logging
import numpy as np 
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, 
    QPushButton, QLabel, QLineEdit, QSizePolicy, QComboBox # Added QComboBox
)
from PySide6.QtCore import Qt, Signal, Slot

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

logger = logging.getLogger(__name__)

class MacroControlView(QWidget):
    start_simulation_signal = Signal()
    parameter_changed = Signal(str, object) # New signal for parameter changes

    def __init__(self, config_data=None, simulation_connector=None, parent=None):
        super().__init__(parent)
        self.config_data = config_data if config_data else {} 
        # Store a deep copy of the initial config to fetch strategy weights
        self.initial_config = json.loads(json.dumps(config_data)) if config_data else {}
        self.simulation_connector = simulation_connector
        self.is_simulation_paused = False
        
        self.time_steps_history = []
        self.user_satisfaction_history = []
        self.operator_profit_history = []
        self.grid_friendliness_history = []
        self.overall_score_history = []
        
        self._init_ui() # Initializes UI elements including QComboBoxes

        if self.simulation_connector:
            self.simulation_connector.connector_step_updated.connect(self.update_simulation_step_display)
            self.simulation_connector.connector_kpis_updated.connect(self.update_kpi_displays)
            self.simulation_connector.connector_status_update.connect(self.update_status_message_display)
            self.simulation_connector.connector_simulation_finished.connect(self.on_simulation_finished_or_reset)
            self.simulation_connector.connector_error_occurred.connect(self.on_simulation_error)
            # Connect to status update for more robust button state handling
            self.simulation_connector.connector_status_update.connect(
                self._handle_status_for_ui_reset 
            )
    
    @Slot(str)
    def _handle_status_for_ui_reset(self, message):
        """Resets UI elements if simulation ends, resets, or errors."""
        if message in ["仿真已重置 (Simulation Reset)", 
                       "仿真正常结束 (Simulation Finished)", 
                       "仿真线程意外终止 (Thread terminated unexpectedly)"] or \
           "仿真错误" in message or "Simulation Error" in message:
            self.on_simulation_finished_or_reset()


    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # Section 1: Simulation Control
        sim_control_group = QGroupBox("仿真控制 (Simulation Control)")
        sim_control_layout = QGridLayout()
        self.start_button = QPushButton("启动 (Start)")
        self.pause_resume_button = QPushButton("暂停 (Pause)")
        self.reset_button = QPushButton("重置 (Reset)")
        self.start_button.setStyleSheet("background-color: #4CAF50; color: white; padding: 5px;")
        self.pause_resume_button.setStyleSheet("background-color: #ff9800; color: white; padding: 5px;")
        self.reset_button.setStyleSheet("background-color: #f44336; color: white; padding: 5px;")

        if self.simulation_connector:
            self.start_button.clicked.connect(self.handle_start_simulation)
            self.pause_resume_button.clicked.connect(self.handle_pause_resume_simulation)
            self.reset_button.clicked.connect(self.handle_reset_simulation)
        else:
            self.start_button.setEnabled(False); self.pause_resume_button.setEnabled(False); self.reset_button.setEnabled(False)

        sim_duration_label = QLabel("仿真时长 (天):")
        env_config = self.config_data.get('environment', {})
        sim_days_value = str(env_config.get('simulation_days', "N/A"))
        self.sim_duration_display = QLabel(sim_days_value)
        self.sim_duration_display.setStyleSheet("font-weight: bold;")
        self.current_step_label = QLabel("当前步数: N/A")
        self.status_message_label = QLabel("状态: 未开始 (Status: Not Started)")
        sim_control_layout.addWidget(self.start_button, 0, 0); sim_control_layout.addWidget(self.pause_resume_button, 0, 1); sim_control_layout.addWidget(self.reset_button, 0, 2)
        sim_control_layout.addWidget(sim_duration_label, 1, 0); sim_control_layout.addWidget(self.sim_duration_display, 1, 1, 1, 2)
        sim_control_layout.addWidget(self.current_step_label, 2, 0, 1, 3); sim_control_layout.addWidget(self.status_message_label, 3, 0, 1, 3)
        sim_control_group.setLayout(sim_control_layout)
        main_layout.addWidget(sim_control_group)

        # Section 2: Parameter Configuration
        param_config_group = QGroupBox("参数配置 (Parameter Configuration)")
        param_config_layout = QGridLayout()
        
        scheduler_config = self.config_data.get('scheduler', {})
        # Use initial_config to populate combo boxes to ensure original options are always available
        strategies_options = list(self.initial_config.get('strategies', {}).keys())
        
        param_config_layout.addWidget(QLabel("策略模式 (Strategy Mode):"), 0, 0)
        self.strategy_combo = QComboBox()
        if strategies_options:
            self.strategy_combo.addItems(strategies_options)
            # Determine current strategy: find which strategy's weights match current scheduler_config weights
            current_opt_weights = scheduler_config.get('optimization_weights', {})
            selected_strategy_name = ""
            for name, weights in self.initial_config.get('strategies', {}).items():
                if weights == current_opt_weights:
                    selected_strategy_name = name
                    break
            if not selected_strategy_name and strategies_options: # Fallback if no match
                 selected_strategy_name = strategies_options[0] 
            self.strategy_combo.setCurrentText(selected_strategy_name)

        self.strategy_combo.currentTextChanged.connect(self._on_strategy_changed)
        param_config_layout.addWidget(self.strategy_combo, 0, 1)

        param_config_layout.addWidget(QLabel("调度算法 (Scheduling Algorithm):"), 1, 0)
        self.algorithm_combo = QComboBox()
        algo_options = list(self.initial_config.get('algorithms', {}).keys())
        if not algo_options: algo_options = ["rule_based", "coordinated_mas", "marl", "uncoordinated"] # Fallback
        self.algorithm_combo.addItems(algo_options)
        self.algorithm_combo.setCurrentText(scheduler_config.get('scheduling_algorithm', algo_options[0]))
        self.algorithm_combo.currentTextChanged.connect(
            lambda text: self.parameter_changed.emit("scheduling_algorithm", text)
        )
        param_config_layout.addWidget(self.algorithm_combo, 1, 1)

        param_config_layout.addWidget(QLabel("MAS状态 (MAS Status):"), 2, 0)
        self.marl_status_display = QLabel("启用 (Enabled)" if scheduler_config.get('use_multi_agent', False) else "禁用 (Disabled)")
        param_config_layout.addWidget(self.marl_status_display, 2, 1)
        
        self.opt_weights_labels = {}
        opt_weights_display = scheduler_config.get('optimization_weights', {}) # Display current weights
        param_config_layout.addWidget(QLabel("用户满意度权重:"), 0, 2)
        self.opt_weights_labels["user_satisfaction"] = QLabel(str(opt_weights_display.get("user_satisfaction", "N/A")))
        param_config_layout.addWidget(self.opt_weights_labels["user_satisfaction"], 0, 3)
        param_config_layout.addWidget(QLabel("运营商利润权重:"), 1, 2)
        self.opt_weights_labels["operator_profit"] = QLabel(str(opt_weights_display.get("operator_profit", "N/A")))
        param_config_layout.addWidget(self.opt_weights_labels["operator_profit"], 1, 3)
        param_config_layout.addWidget(QLabel("电网友好度权重:"), 2, 2)
        self.opt_weights_labels["grid_friendliness"] = QLabel(str(opt_weights_display.get("grid_friendliness", "N/A")))
        param_config_layout.addWidget(self.opt_weights_labels["grid_friendliness"], 2, 3)
        
        param_config_group.setLayout(param_config_layout)
        main_layout.addWidget(param_config_group)
        self.parameter_widgets = [self.strategy_combo, self.algorithm_combo] 

        # Section 3: Key Performance Indicators (KPIs)
        kpi_group = QGroupBox("关键性能指标 (Key Performance Indicators)")
        kpi_layout = QGridLayout()
        self.kpi_labels = {} 
        kpis_to_display = {
            "user_satisfaction": "用户满意度 (User Satisfaction):",
            "operator_profit": "运营商利润 (Operator Profit):",
            "grid_friendliness": "电网友好度 (Grid Friendliness):"
        }
        row = 0
        for key, text in kpis_to_display.items():
            label = QLabel(text)
            value_label = QLabel("N/A") 
            value_label.setStyleSheet("font-weight: bold; color: #007bff;")
            kpi_layout.addWidget(label, row, 0)
            kpi_layout.addWidget(value_label, row, 1)
            self.kpi_labels[key] = value_label 
            row += 1
        overall_score_label = QLabel("综合评分 (Overall Score):")
        self.kpi_labels["overall_score"] = QLabel("N/A")
        self.kpi_labels["overall_score"].setStyleSheet("font-weight: bold; color: #007bff;")
        kpi_layout.addWidget(overall_score_label, row, 0)
        kpi_layout.addWidget(self.kpi_labels["overall_score"], row, 1)
        kpi_group.setLayout(kpi_layout)
        main_layout.addWidget(kpi_group)

        # Section 4: KPI Time Series Chart
        chart_group = QGroupBox("KPI图表 (KPI Chart)")
        chart_layout = QVBoxLayout()
        self.kpi_chart_figure = Figure(figsize=(5, 3)) 
        self.kpi_chart_canvas = FigureCanvas(self.kpi_chart_figure)
        self.kpi_chart_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.kpi_chart_axes = self.kpi_chart_figure.add_subplot(111)
        self._setup_kpi_chart()
        self.kpi_chart_figure.tight_layout()
        chart_layout.addWidget(self.kpi_chart_canvas)
        chart_group.setLayout(chart_layout)
        main_layout.addWidget(chart_group)
        
        main_layout.addStretch(1)
        self.setLayout(main_layout)
        self.setStyleSheet(self._get_stylesheet())

    def _on_strategy_changed(self, strategy_name):
        """Handles strategy ComboBox change."""
        logger.debug(f"Strategy changed to: {strategy_name}")
        # Emit the strategy name. Connector will handle fetching weights from initial_config.
        self.parameter_changed.emit("strategy_mode", strategy_name)
        # Update displayed weights based on newly selected strategy
        new_weights = self.initial_config.get('strategies', {}).get(strategy_name, {})
        self.opt_weights_labels["user_satisfaction"].setText(str(new_weights.get("user_satisfaction", "N/A")))
        self.opt_weights_labels["operator_profit"].setText(str(new_weights.get("operator_profit", "N/A")))
        self.opt_weights_labels["grid_friendliness"].setText(str(new_weights.get("grid_friendliness", "N/A")))


    def _get_stylesheet(self):
        return """
            QGroupBox {
                font-size: 14px; font-weight: bold; border: 1px solid gray;
                border-radius: 5px; margin-top: 0.5em;
            }
            QGroupBox::title {
                subcontrol-origin: margin; subcontrol-position: top left;
                padding: 0 3px 0 3px; background-color: transparent;
            }
            QLabel { font-size: 12px; }
            QPushButton { font-size: 12px; min-height: 25px; }
            QComboBox { font-size: 12px; min-height: 25px; padding: 2px 5px; }
        """

    def _setup_kpi_chart(self, clear_data=False):
        if clear_data:
            self.time_steps_history.clear(); self.user_satisfaction_history.clear()
            self.operator_profit_history.clear(); self.grid_friendliness_history.clear()
            self.overall_score_history.clear()
        self.kpi_chart_axes.clear()
        if self.time_steps_history:
            self.kpi_chart_axes.plot(self.time_steps_history, self.user_satisfaction_history, label="用户满意度", marker='.')
            self.kpi_chart_axes.plot(self.time_steps_history, self.operator_profit_history, label="运营商利润", marker='.')
            self.kpi_chart_axes.plot(self.time_steps_history, self.grid_friendliness_history, label="电网友好度", marker='.')
            self.kpi_chart_axes.plot(self.time_steps_history, self.overall_score_history, label="综合评分", marker='.', linestyle='--')
        self.kpi_chart_axes.set_title("KPI变化趋势 (KPI Trend)")
        self.kpi_chart_axes.set_xlabel("时间步 (Time Step)"); self.kpi_chart_axes.set_ylabel("指标值 (Value)")
        self.kpi_chart_axes.legend(fontsize='small'); self.kpi_chart_axes.grid(True)
        try: self.kpi_chart_figure.tight_layout()
        except ValueError: pass
        self.kpi_chart_canvas.draw()

    @Slot(dict)
    def update_kpi_displays(self, kpi_data):
        if not isinstance(kpi_data, dict):
            logger.warning(f"MacroControlView: Invalid kpi_data format: {type(kpi_data)}. Expected dict.")
            return
        self.kpi_labels["user_satisfaction"].setText(f"{kpi_data.get('user_satisfaction', 0):.3f}")
        self.kpi_labels["operator_profit"].setText(f"{kpi_data.get('operator_profit', 0):.2f}")
        self.kpi_labels["grid_friendliness"].setText(f"{kpi_data.get('grid_friendliness', 0):.3f}")
        self.kpi_labels["overall_score"].setText(f"{kpi_data.get('total_reward', 0):.2f}")
        try:
            current_step_text = self.current_step_label.text().split(':')[-1].strip()
            current_step = int(current_step_text) if current_step_text != "N/A" else (len(self.time_steps_history) + 1)
        except ValueError: current_step = len(self.time_steps_history) + 1
        self.time_steps_history.append(current_step)
        self.user_satisfaction_history.append(kpi_data.get('user_satisfaction', 0))
        self.operator_profit_history.append(kpi_data.get('operator_profit', 0))
        self.grid_friendliness_history.append(kpi_data.get('grid_friendliness', 0))
        self.overall_score_history.append(kpi_data.get('total_reward', 0))
        max_history = 100 
        if len(self.time_steps_history) > max_history:
            for lst in [self.time_steps_history, self.user_satisfaction_history, self.operator_profit_history, self.grid_friendliness_history, self.overall_score_history]:
                del lst[0]
        self._setup_kpi_chart(clear_data=False)

    def handle_start_simulation(self):
        if self.simulation_connector:
            self._setup_kpi_chart(clear_data=True)
            self.simulation_connector.start_simulation()
            self._set_controls_running_state(True)
            self.start_simulation_signal.emit() 

    def handle_pause_resume_simulation(self):
        if not self.simulation_connector: return
        if self.is_simulation_paused:
            self.simulation_connector.resume_simulation()
            self.pause_resume_button.setText("暂停 (Pause)")
            self.is_simulation_paused = False
        else:
            self.simulation_connector.pause_simulation()
            self.pause_resume_button.setText("继续 (Resume)")
            self.is_simulation_paused = True

    def handle_reset_simulation(self):
        if self.simulation_connector:
            self.simulation_connector.reset_simulation()
            # UI state reset is now handled by on_simulation_finished_or_reset via status update

    @Slot(int)
    def update_simulation_step_display(self, current_step):
        self.current_step_label.setText(f"当前步数: {current_step}")

    @Slot(str)
    def update_status_message_display(self, message):
        self.status_message_label.setText(f"状态: {message}")
        # No longer directly calling on_simulation_finished_or_reset here,
        # rely on _handle_status_for_ui_reset for specific messages.

    def on_simulation_finished_or_reset(self):
        self._set_controls_running_state(False)
        self.current_step_label.setText("当前步数: 0")
        self._setup_kpi_chart(clear_data=True)

    @Slot(str)
    def on_simulation_error(self, error_message):
        self.status_message_label.setText(f"错误: {error_message} (Error)")
        self.on_simulation_finished_or_reset() # Also reset UI controls

    def _set_controls_running_state(self, is_running: bool):
        """Helper to enable/disable controls based on simulation state."""
        self.start_button.setEnabled(not is_running)
        self.pause_resume_button.setEnabled(is_running)
        self.reset_button.setEnabled(is_running) # Typically enabled when running
        if not is_running:
            self.pause_resume_button.setText("暂停 (Pause)")
            self.is_simulation_paused = False
        self._set_parameter_widgets_enabled(not is_running)

    def _set_parameter_widgets_enabled(self, enabled: bool):
        for widget in self.parameter_widgets:
            widget.setEnabled(enabled)

if __name__ == '__main__':
    import sys
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QObject # For DummyConnector
    
    logging.basicConfig(level=logging.DEBUG)
    test_config_data = {}
    try:
        with open('../config.json', 'r') as f: 
            test_config_data = json.load(f)
    except Exception as e:
        logger.error(f"Standalone test: Failed to load config: {e}")
        
    app = QApplication(sys.argv)
    
    class DummyConnector(QObject):
        connector_step_updated = Signal(int)
        connector_kpis_updated = Signal(dict)
        connector_status_update = Signal(str)
        connector_simulation_finished = Signal()
        connector_error_occurred = Signal(str)

        def __init__(self): super().__init__()
        def start_simulation(self): logger.info("Dummy Start"); self.connector_status_update.emit("Dummy Started")
        def pause_simulation(self): logger.info("Dummy Pause"); self.connector_status_update.emit("Dummy Paused")
        def resume_simulation(self): logger.info("Dummy Resume"); self.connector_status_update.emit("Dummy Resumed")
        def reset_simulation(self): 
            logger.info("Dummy Reset")
            self.connector_status_update.emit("仿真已重置 (Simulation Reset)")
            self.connector_kpis_updated.emit({})
        @Slot(str, object)
        def update_simulation_parameter(self, name, value): # Slot to receive parameter changes
            logger.info(f"DummyConnector: Received parameter change: {name} = {value}")

    dummy_connector_instance = DummyConnector()
    view = MacroControlView(config_data=test_config_data, simulation_connector=dummy_connector_instance)
    view.parameter_changed.connect(dummy_connector_instance.update_simulation_parameter) # Connect signal
    
    view.setWindowTitle("Test Macro Control View (Standalone with Dummy Connector)")
    view.resize(650, 800) 
    view.show()
    
    from PySide6.QtCore import QTimer
    def test_signals():
        import time, numpy as np
        dummy_connector_instance.start_simulation()
        for i in range(10):
            time.sleep(0.2)
            dummy_connector_instance.connector_step_updated.emit(i + 1)
            kpi_data_point = {'user_satisfaction': 0.7+np.random.rand()*0.1, 'operator_profit': 120+np.random.rand()*20, 'grid_friendliness': 0.8+np.random.rand()*0.1, 'total_reward': 200+np.random.rand()*30}
            dummy_connector_instance.connector_kpis_updated.emit(kpi_data_point)
            if i == 3: dummy_connector_instance.pause_simulation(); time.sleep(0.5); dummy_connector_instance.resume_simulation()
        dummy_connector_instance.connector_simulation_finished.emit()
    QTimer.singleShot(1000, test_signals) 
    
    sys.exit(app.exec())
