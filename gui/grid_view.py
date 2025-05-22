import sys
import logging
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel, QTableWidget, 
    QTableWidgetItem, QHeaderView, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Slot # Import Slot explicitly
from PySide6.QtGui import QColor

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas

logger = logging.getLogger(__name__)

class GridView(QWidget):
    MAX_CHART_HISTORY = 100 # Max data points for line charts

    def __init__(self, config_data=None, simulation_connector=None, parent=None):
        super().__init__(parent)
        self.config_data = config_data if config_data else {}
        self.simulation_connector = simulation_connector
        self.region_ids = self._get_region_ids_from_config()

        # Initialize data storage for charts
        self.time_steps_history = []
        self.num_regions_to_plot_line = min(len(self.region_ids), 3) # Plot up to 3 regions' total load
        self.regional_total_load_history = {
            rid: [] for rid in self.region_ids[:self.num_regions_to_plot_line]
        }
        self.current_regional_ev_load_data = {rid: 0 for rid in self.region_ids} # For bar chart

        self._init_ui()

        if self.simulation_connector:
            self.simulation_connector.connector_grid_status_updated.connect(self.update_grid_displays)
            self.simulation_connector.connector_step_updated.connect(self.add_time_step_to_history)


    def _get_region_ids_from_config(self):
        if not self.config_data:
            logger.warning("GridView: No config_data. Defaulting to 0 regions.")
            return []
        grid_config = self.config_data.get('grid', {})
        # Try to get region IDs from a regionalized config key, e.g., 'base_load'
        # which should be a dictionary with region_ids as keys.
        regional_data_source = grid_config.get('base_load', {}) # Default to base_load as a source
        if not isinstance(regional_data_source, dict) or not regional_data_source.keys():
             # Fallback: if base_load is not a dict or empty, try 'system_capacity_regional'
             regional_data_source = grid_config.get('system_capacity_regional', {})
        
        if isinstance(regional_data_source, dict) and regional_data_source.keys():
            region_ids = list(regional_data_source.keys())
            logger.info(f"GridView: Region IDs derived from grid config keys: {region_ids}")
            return sorted(region_ids) 
        
        # Fallback to environment.region_count if grid keys are not available
        env_config = self.config_data.get('environment', {})
        region_count = env_config.get('region_count', 0)
        if isinstance(region_count, int) and region_count > 0:
            default_ids = [f"region_{i}" for i in range(region_count)]
            logger.warning(f"GridView: Region IDs derived from 'environment.region_count': {default_ids} as regional grid data keys were not found.")
            return default_ids
            
        logger.error("GridView: Cannot determine regions from config. No regions will be displayed.")
        return []

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)

        # Section 1: Overall Grid Section
        overall_grid_group = QGroupBox("总体电网状态 (Overall Grid Status)")
        overall_grid_layout = QGridLayout()

        self.total_grid_load_label = QLabel("总电网负载 (MW): N/A")
        self.total_ev_load_label = QLabel("总电动汽车负载 (MW): N/A")
        self.renewable_contrib_label = QLabel("可再生能源贡献 (%): N/A")
        
        overall_grid_layout.addWidget(self.total_grid_load_label, 0, 0)
        overall_grid_layout.addWidget(self.total_ev_load_label, 0, 1)
        overall_grid_layout.addWidget(self.renewable_contrib_label, 0, 2)
        
        overall_grid_group.setLayout(overall_grid_layout)
        main_layout.addWidget(overall_grid_group)

        # Section 2: Regional Load Display Section
        regional_display_group = QGroupBox("区域负载详情 (Regional Load Details)")
        regional_display_layout = QVBoxLayout()

        # 2a: Regional Data Table
        self.regional_table = QTableWidget()
        self.regional_table.setColumnCount(8)
        self.regional_table.setHorizontalHeaderLabels([
            "区域ID", "基础负载 (MW)", "EV负载 (MW)", "总负载 (MW)", 
            "负载率 (%)", "太阳能 (MW)", "风能 (MW)", "可再生能源占比 (%)"
        ])
        
        num_regions = len(self.region_ids)
        self.regional_table.setRowCount(num_regions if num_regions > 0 else 1)
        self.regional_table.verticalHeader().setVisible(False)
        self.regional_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.regional_table.setMinimumHeight(max(100, num_regions * 35 + 35))
        self._populate_initial_table() # This method needs to be defined
        regional_display_layout.addWidget(self.regional_table)

        # 2b: Regional Load Charts (Matplotlib)
        charts_layout = QHBoxLayout() # Horizontal layout for two charts

        # Chart 1: Regional Load Curves
        self.load_curve_figure = Figure(figsize=(5, 3.5))
        self.load_curve_canvas = FigureCanvas(self.load_curve_figure)
        self.load_curve_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.load_curve_axes = self.load_curve_figure.add_subplot(111)
        self._setup_load_curve_chart(clear_data=True)
        charts_layout.addWidget(self.load_curve_canvas)

        # Chart 2: Regional Comparison (Bar Chart)
        self.comparison_figure = Figure(figsize=(5, 3.5))
        self.comparison_canvas = FigureCanvas(self.comparison_figure)
        self.comparison_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.comparison_axes = self.comparison_figure.add_subplot(111)
        self._setup_comparison_bar_chart(clear_data=True)
        charts_layout.addWidget(self.comparison_canvas)
        
        regional_display_layout.addLayout(charts_layout)
        
        # 2c: Simplified Map Placeholder
        map_placeholder_group = QGroupBox("区域状态概览 (Region Status Overview)")
        map_layout = QGridLayout()
        map_layout.setSpacing(5)
        self.region_status_labels = {}
        
        status_colors_initial = ["#bdc3c7"] * len(self.region_ids) # Default to gray
        
        if not self.region_ids:
            map_layout.addWidget(QLabel("无区域数据 (No Region Data)"), 0, 0, 1, 4)
        else:
            cols = 4 
            for i, region_id in enumerate(self.region_ids):
                region_label = QLabel(f"{region_id}\nN/A %")
                region_label.setAlignment(Qt.AlignCenter)
                region_label.setFrameShape(QFrame.StyledPanel)
                region_label.setMinimumSize(80, 50)
                region_label.setStyleSheet(
                    f"background-color: {status_colors_initial[i]}; color: black; " # Black text for light gray
                    f"font-weight: bold; border-radius: 4px; padding: 5px;"
                )
                self.region_status_labels[region_id] = region_label
                map_layout.addWidget(region_label, i // cols, i % cols)
        
        map_placeholder_group.setLayout(map_layout)
        regional_display_layout.addWidget(map_placeholder_group)

        regional_display_group.setLayout(regional_display_layout)
        main_layout.addWidget(regional_display_group)

        # Section 3: Other Metrics
        other_metrics_group = QGroupBox("其他指标 (Other Metrics)")
        other_metrics_layout = QHBoxLayout()
        self.carbon_intensity_label = QLabel("碳排放强度 (gCO2/kWh): N/A")
        other_metrics_layout.addWidget(self.carbon_intensity_label)
        other_metrics_group.setLayout(other_metrics_layout)
        main_layout.addWidget(other_metrics_group)

        main_layout.addStretch(1) # Push content to the top
        self.setLayout(main_layout)
        
        self.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-weight: bold;
                border: 1px solid gray;
                border-radius: 5px;
                margin-top: 0.5em;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 3px 0 3px;
            }
            QLabel {
                font-size: 12px;
            }
            QTableWidget {
                font-size: 11px;
                border: 1px solid #cccccc;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                padding: 4px;
                border-style: none;
                border-bottom: 1px solid #cccccc;
                border-right: 1px solid #cccccc;
                font-size: 12px;
            }
        """)

    def add_time_step_to_history(self, step_number):
        """Adds current step number to time_steps_history for X-axis of line chart."""
        self.time_steps_history.append(step_number)
        if len(self.time_steps_history) > self.MAX_CHART_HISTORY:
            self.time_steps_history.pop(0)
            for region_id_hist in self.regional_total_load_history: 
                if self.regional_total_load_history[region_id_hist]: 
                    self.regional_total_load_history[region_id_hist].pop(0)

    def _populate_initial_table(self):
        """Populates the table with N/A or initial data from config if available."""
        if not self.region_ids:
            for col in range(self.regional_table.columnCount()): 
                item = QTableWidgetItem("N/A")
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.regional_table.setItem(0, col, item)
            return

        grid_config = self.config_data.get('grid', {})
        # Get base_load and system_capacity for initial display if available
        base_load_profiles = grid_config.get('base_load', {})
        system_capacities = grid_config.get('system_capacity_kw', {})
        solar_profiles = grid_config.get('solar_generation', {})
        wind_profiles = grid_config.get('wind_generation', {})


        for row, region_id in enumerate(self.region_ids):
            # Ensure row exists (it should, as table is sized based on self.region_ids)
            if row >= self.regional_table.rowCount(): continue

            # Initial values (e.g., for hour 0 or averages)
            base_load_val = base_load_profiles.get(region_id, [0])[0] if base_load_profiles.get(region_id) else 0
            solar_val = solar_profiles.get(region_id, [0])[0] if solar_profiles.get(region_id) else 0
            wind_val = wind_profiles.get(region_id, [0])[0] if wind_profiles.get(region_id) else 0
            ev_load_val = 0.0 # EV load is initially zero
            total_load_val = base_load_val + ev_load_val
            capacity_val = system_capacities.get(region_id, 1) # Avoid div by zero, default to 1 if missing
            load_percent_val = (total_load_val / capacity_val) * 100 if capacity_val > 0 else 0
            renew_total_val = solar_val + wind_val
            renew_ratio_val = (renew_total_val / total_load_val) * 100 if total_load_val > 0 else 0
            
            # Create and set items for each cell
            self.regional_table.setItem(row, 0, QTableWidgetItem(region_id))
            self.regional_table.setItem(row, 1, QTableWidgetItem(f"{base_load_val:.1f}"))
            self.regional_table.setItem(row, 2, QTableWidgetItem(f"{ev_load_val:.1f}"))
            self.regional_table.setItem(row, 3, QTableWidgetItem(f"{total_load_val:.1f}"))
            self.regional_table.setItem(row, 4, QTableWidgetItem(f"{load_percent_val:.1f}%"))
            self.regional_table.setItem(row, 5, QTableWidgetItem(f"{solar_val:.1f}"))
            self.regional_table.setItem(row, 6, QTableWidgetItem(f"{wind_val:.1f}"))
            self.regional_table.setItem(row, 7, QTableWidgetItem(f"{renew_ratio_val:.1f}%"))

            for col in range(self.regional_table.columnCount()):
                item = self.regional_table.item(row, col)
                if item: # Ensure item exists
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable) # Make cells read-only

    def _setup_load_curve_chart(self, clear_data=False):
        if clear_data:
            self.time_steps_history.clear()
            for region_id_hist in self.regional_total_load_history:
                self.regional_total_load_history[region_id_hist].clear()

        self.load_curve_axes.clear()
        for i, region_id_to_plot in enumerate(self.regional_total_load_history.keys()):
            if self.time_steps_history and self.regional_total_load_history[region_id_to_plot]:
                self.load_curve_axes.plot(self.time_steps_history, self.regional_total_load_history[region_id_to_plot], 
                                          label=f"{region_id_to_plot} 总负载")
        
        self.load_curve_axes.set_title("区域总负载曲线 (Regional Total Load Curves)")
        self.load_curve_axes.set_xlabel("时间步 (Time Step)")
        self.load_curve_axes.set_ylabel("总负载 (MW)")
        if any(self.regional_total_load_history.values()): self.load_curve_axes.legend(fontsize='small')
        self.load_curve_axes.grid(True)
        try: self.load_curve_figure.tight_layout()
        except ValueError: pass
        self.load_curve_canvas.draw()

    def _setup_comparison_bar_chart(self, clear_data=False):
        if clear_data:
            self.current_regional_ev_load_data = {rid: 0 for rid in self.region_ids}

        self.comparison_axes.clear()
        if self.region_ids: 
            region_labels = [rid.replace("region_", "R") for rid in self.region_ids]
            ev_loads = [self.current_regional_ev_load_data.get(rid, 0) for rid in self.region_ids]
            self.comparison_axes.bar(region_labels, ev_loads, color='mediumpurple')
        
        self.comparison_axes.set_title("各区域当前EV负载 (Current EV Load by Region)")
        self.comparison_axes.set_xlabel("区域 (Region)")
        self.comparison_axes.set_ylabel("EV负载 (MW)")
        self.comparison_axes.tick_params(axis='x', rotation=30, labelsize='small')
        self.comparison_axes.grid(axis='y')
        try: self.comparison_figure.tight_layout()
        except ValueError: pass
        self.comparison_canvas.draw()

    @Slot(dict)
    def update_grid_displays(self, grid_data):
        logger.debug(f"GridView: Updating displays with grid_data keys: {list(grid_data.keys())}")

        if not grid_data: 
            self._populate_initial_table() 
            self._setup_load_curve_chart(clear_data=True)
            self._setup_comparison_bar_chart(clear_data=True)
            for region_id in self.region_ids:
                if region_id in self.region_status_labels:
                    self.region_status_labels[region_id].setText(f"{region_id.replace('region_','R')}\nN/A %")
                    self.region_status_labels[region_id].setStyleSheet(
                        "background-color: #bdc3c7; color: black; font-weight: bold; border-radius: 4px; padding: 5px;"
                    )
            self.total_grid_load_label.setText("总电网负载 (MW): N/A")
            self.total_ev_load_label.setText("总电动汽车负载 (MW): N/A")
            self.renewable_contrib_label.setText("可再生能源贡献 (%): N/A")
            return

        current_total_load_regional = grid_data.get('current_total_load_regional', {})
        current_ev_load_regional = grid_data.get('current_ev_load_regional', {})
        current_solar_gen_regional = grid_data.get('current_solar_gen_regional', {})
        current_wind_gen_regional = grid_data.get('current_wind_gen_regional', {})

        total_grid_load = sum(current_total_load_regional.values())
        total_ev_load = sum(current_ev_load_regional.values())
        total_solar_gen = sum(current_solar_gen_regional.values())
        total_wind_gen = sum(current_wind_gen_regional.values())
        total_renewable_gen = total_solar_gen + total_wind_gen
        overall_renewable_contrib = (total_renewable_gen / total_grid_load * 100) if total_grid_load > 0 else 0

        self.total_grid_load_label.setText(f"总电网负载 (MW): {total_grid_load:.2f}")
        self.total_ev_load_label.setText(f"总电动汽车负载 (MW): {total_ev_load:.2f}")
        self.renewable_contrib_label.setText(f"可再生能源贡献 (%): {overall_renewable_contrib:.1f}%")

        for row, region_id in enumerate(self.region_ids):
            if row >= self.regional_table.rowCount(): continue

            base_load = grid_data.get('current_base_load_regional', {}).get(region_id, 0)
            ev_load = current_ev_load_regional.get(region_id, 0)
            total_load = current_total_load_regional.get(region_id, 0)
            load_percent = grid_data.get('grid_load_percentage_regional', {}).get(region_id, 0)
            solar_gen = current_solar_gen_regional.get(region_id, 0)
            wind_gen = current_wind_gen_regional.get(region_id, 0)
            renew_ratio = grid_data.get('renewable_ratio_regional', {}).get(region_id, 0)
            
            # Ensure QTableWidgetItems exist, create if not (should be handled by _populate_initial_table)
            for col in range(self.regional_table.columnCount()):
                if not self.regional_table.item(row, col):
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.regional_table.setItem(row, col, item)

            self.regional_table.item(row, 0).setText(region_id)
            self.regional_table.item(row, 1).setText(f"{base_load:.1f}")
            self.regional_table.item(row, 2).setText(f"{ev_load:.1f}")
            self.regional_table.item(row, 3).setText(f"{total_load:.1f}")
            self.regional_table.item(row, 4).setText(f"{load_percent:.1f}%")
            self.regional_table.item(row, 5).setText(f"{solar_gen:.1f}")
            self.regional_table.item(row, 6).setText(f"{wind_gen:.1f}")
            self.regional_table.item(row, 7).setText(f"{renew_ratio:.1f}%")
            
            if region_id in self.regional_total_load_history:
                self.regional_total_load_history[region_id].append(total_load)
                if len(self.regional_total_load_history[region_id]) > self.MAX_CHART_HISTORY:
                    self.regional_total_load_history[region_id].pop(0)
            
            if region_id in self.current_regional_ev_load_data:
                self.current_regional_ev_load_data[region_id] = ev_load

            if region_id in self.region_status_labels:
                color = "#bdc3c7"; text_color = "black" 
                if load_percent > 75: color = "#e74c3c"; text_color = "white"
                elif load_percent > 50: color = "#f39c12"; text_color = "white"
                elif load_percent > 0 : color = "#2ecc71"; text_color = "white"
                
                self.region_status_labels[region_id].setText(f"{region_id.replace('region_','R')}\n{load_percent:.0f}%")
                self.region_status_labels[region_id].setStyleSheet(
                    f"background-color: {color}; color: {text_color}; font-weight: bold; border-radius: 4px; padding: 5px;"
                )
        
        self._setup_load_curve_chart(clear_data=False)
        self._setup_comparison_bar_chart(clear_data=False)


if __name__ == '__main__':
    # --- Imports for standalone testing ---
    from PySide6.QtWidgets import QApplication # Corrected import location for test
    from PySide6.QtCore import QObject, Signal, QTimer # Corrected import location for test
    # --- End imports for standalone testing ---

    app = QApplication(sys.argv)
    logging.basicConfig(level=logging.DEBUG)
    mock_config_for_gridview = {
        "environment": {"region_count": 8}, 
        "grid": {
            "base_load": {f"region_{i}": [100+i*10]*24 for i in range(8)},
            "solar_generation": {f"region_{i}": [20+i*5]*24 for i in range(8)},
            "wind_generation": {f"region_{i}": [30+i*3]*24 for i in range(8)},
            "system_capacity_kw": {f"region_{i}": 200+i*20 for i in range(8)}
        }
    }
    
    class DummyConnector(QObject):
        connector_grid_status_updated = Signal(dict)
        connector_step_updated = Signal(int)
        def __init__(self): super().__init__()
        def reset_simulation(self): self.connector_grid_status_updated.emit({})

    dummy_connector_instance = DummyConnector()
    view = GridView(config_data=mock_config_for_gridview, simulation_connector=dummy_connector_instance)
    view.setWindowTitle("Test Grid View (Standalone with Dummy Connector)")
    view.resize(850, 900)
    view.show()

    def simulate_data_updates():
        import time, random
        for step in range(1, 25):
            dummy_connector_instance.connector_step_updated.emit(step)
            mock_grid_data = {
                'current_base_load_regional': {rid: 70 + random.randint(0,80) for rid in view.region_ids},
                'current_ev_load_regional': {rid: 5 + random.randint(0,45) for rid in view.region_ids},
                'current_total_load_regional': {rid: 100 + random.randint(0,100) for rid in view.region_ids},
                'grid_load_percentage_regional': {rid: 30 + random.randint(0,60) for rid in view.region_ids},
                'current_solar_gen_regional': {rid: random.randint(0,80) for rid in view.region_ids},
                'current_wind_gen_regional': {rid: random.randint(0,70) for rid in view.region_ids},
                'renewable_ratio_regional': {rid: 10 + random.randint(0,50) for rid in view.region_ids},
            }
            dummy_connector_instance.connector_grid_status_updated.emit(mock_grid_data)
            time.sleep(0.5)

    QTimer.singleShot(1000, simulate_data_updates)

    sys.exit(app.exec())
