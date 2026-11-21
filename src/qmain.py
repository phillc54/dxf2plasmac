import sys

from PyQt5.QtCore import Qt
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.dxf_gui = dxfGui('/Volumes/CaseSensitiveHD/git/dxf2plasmac/testing/test_material.cfg')
        layout.addWidget(self.dxf_gui)

        self.dxf_gui.D2P.material_file = '/Volumes/CaseSensitiveHD/git/dxf2plasmac/testing/test_material.cfg'
        self.dxf_gui.D2P.units = 'metric'
        self.dxf_gui.D2P.lead_type = 'arc'
        self.dxf_gui.D2P.lead_length = 3.0
        self.dxf_gui.D2P.last_cut = (0.0, 0.0)
        self.dxf_gui.D2P.flattening_distance = 0.025
        self.dxf_gui.D2P.gap_tolerance = 0.001
        self.dxf_gui.D2P.lead_angle = 45
        self.dxf_gui.D2P.precision = 2
        self.dxf_gui.D2P.small_hole = 32
        self.dxf_gui.shape_color = Qt.black
        self.dxf_gui.rapid_color = Qt.darkYellow
        self.dxf_gui.leadin_color = Qt.cyan
        self.dxf_gui.cut_color_external  = Qt.red
        self.dxf_gui.cut_color_internal = Qt.green
        self.dxf_gui.invalid_color  = Qt.magenta
        self.dxf_gui.selectedColor = Qt.yellow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
