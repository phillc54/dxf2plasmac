import sys

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from .dxf_to_plasmac_gui import dxfGui


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('dxf2QtPlasmaC')
        self.resize(1000, 650)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        self.dxf_gui = dxfGui()
        layout.addWidget(self.dxf_gui)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
