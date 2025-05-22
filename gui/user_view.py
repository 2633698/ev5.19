import sys
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

class UserView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter) # Center content in the layout

        self.placeholder_label = QLabel(
            "用户视图 (User View)\n\n(功能待开发 - Functionality to be developed)"
        )
        self.placeholder_label.setAlignment(Qt.AlignCenter) # Center text within the label
        
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        self.placeholder_label.setFont(font)
        
        self.placeholder_label.setStyleSheet("color: #555555; padding: 20px;")

        layout.addWidget(self.placeholder_label)
        self.setLayout(layout)

if __name__ == '__main__':
    # This part is for testing the widget independently
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    view = UserView()
    view.setWindowTitle("Test User View")
    view.resize(400, 300)
    view.show()
    sys.exit(app.exec())
