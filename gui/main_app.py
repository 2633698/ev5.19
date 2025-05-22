import sys
import json
import logging 
from PySide6.QtWidgets import QApplication, QMainWindow, QStatusBar, QLabel, QTabWidget, QWidget
from PySide6.QtCore import Qt
from gui.macro_control_view import MacroControlView
from gui.grid_view import GridView
from gui.user_view import UserView
from gui.operator_view import OperatorView
from gui.simulation_connector import SimulationConnector

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("电动汽车充电调度仿真系统 (EV Charging Dispatch Simulation System)")
        self.setGeometry(100, 100, 950, 850)

        self.config_data = self._load_configuration()
        self.simulation_connector = SimulationConnector(initial_config=self.config_data) # Pass initial_config

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self.macro_control_tab = MacroControlView(
            config_data=self.config_data, # Pass initial config for display setup
            simulation_connector=self.simulation_connector 
        )
        self.tab_widget.addTab(self.macro_control_tab, "宏观控制 (Macro Control)")

        self.grid_view_tab = GridView(
            config_data=self.config_data, # Pass initial config for display setup
            simulation_connector=self.simulation_connector # Pass connector for live grid updates
        ) 
        self.tab_widget.addTab(self.grid_view_tab, "电网视图 (Grid View)")

        self.user_view_tab = UserView()
        self.tab_widget.addTab(self.user_view_tab, "用户视图 (User View)")

        self.operator_view_tab = OperatorView()
        self.tab_widget.addTab(self.operator_view_tab, "运营商视图 (Operator View)")
        
        self._setup_menu_and_status_bar()
        self._connect_signals()

    def _load_configuration(self):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                logger.info("config.json loaded successfully.")
                return config
        except FileNotFoundError:
            logger.error("config.json not found. Application might not function as expected.")
            return {} 
        except json.JSONDecodeError:
            logger.error("Error decoding config.json. Check its format.")
            return {}
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading config.json: {e}")
            return {}

    def _setup_menu_and_status_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&文件 (File)")
        exit_action = file_menu.addAction("退出 (Exit)")
        exit_action.triggered.connect(self.close)
        
        help_menu = menu_bar.addMenu("&帮助 (Help)")
        about_action = help_menu.addAction("关于 (About)")
        # about_action.triggered.connect(self.show_about_dialog) 

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("准备就绪 (Ready)")

    def _connect_signals(self):
        # Connect MacroControlView's parameter_changed signal to SimulationConnector's slot
        if hasattr(self.macro_control_tab, 'parameter_changed') and hasattr(self.simulation_connector, 'update_simulation_parameter'):
            self.macro_control_tab.parameter_changed.connect(self.simulation_connector.update_simulation_parameter)
            logger.info("Connected MacroControlView.parameter_changed to SimulationConnector.update_simulation_parameter")

        # Status bar updates from MacroControlView (button clicks)
        if hasattr(self.macro_control_tab, 'start_simulation_signal'):
             self.macro_control_tab.start_simulation_signal.connect(
                 lambda: self.statusBar().showMessage("仿真启动指令已发送 (Start command sent)")
             )
        # Note: Pause/Resume status messages are now better handled by connector_status_update
        # if hasattr(self.macro_control_tab, 'pause_simulation_signal'): # This signal might be removed/obsolete
        #     self.macro_control_tab.pause_simulation_signal.connect(
        #         lambda: self.statusBar().showMessage("仿真暂停指令已发送 (Pause command sent)")
        #     )
        # if hasattr(self.macro_control_tab, 'reset_simulation_signal'): # This signal might be removed/obsolete
        #     self.macro_control_tab.reset_simulation_signal.connect(
        #         lambda: self.statusBar().showMessage("仿真重置指令已发送 (Reset command sent)")
        #     )
        
        # More general status updates from the connector itself
        if hasattr(self.simulation_connector, 'connector_status_update'):
            self.simulation_connector.connector_status_update.connect(
                lambda msg: self.statusBar().showMessage(f"状态: {msg}")
            )

        self.tab_widget.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index):
        tab_title = self.tab_widget.tabText(index)
        self.statusBar().showMessage(f"切换到标签页: {tab_title} (Switched to tab: {tab_title})")

    # def show_about_dialog(self):
    #     from PySide6.QtWidgets import QMessageBox 
    #     QMessageBox.about(self, "关于 (About)", "电动汽车充电调度仿真系统 v0.1\nEV Charging Dispatch Simulation System v0.1")

def main():
    # Configure logging at the application entry point
    logging.basicConfig(
        level=logging.DEBUG, # Set to DEBUG to capture all levels of logs
        format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[
            logging.FileHandler("gui_app.log", mode='w'), # Log to a file
            logging.StreamHandler() # Log to console
        ]
    )
    logger.info("Application starting...")
    app = QApplication(sys.argv)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
