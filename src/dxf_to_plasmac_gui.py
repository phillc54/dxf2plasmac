import math
import os
import sys
from pathlib import Path
from typing import override

from PyQt5.QtCore import (
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .dxf_to_plasmac import dxf2PlasmaC

TAG_KEY = 0


def get_asset_path(relative_path: str) -> str:
    ''' resolves paths for local pixi development and compiled pyinstaller bundles '''
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class SelectablePathItem(QGraphicsPathItem):
    '''A custom line/arc item with tags and selection styling.'''
    def __init__(self, path: QPainterPath, tags: list[str], color: QColor=Qt.blue):
        super().__init__(path)
        self.default_pen = QPen(color, 2)
        self.selected_pen = QPen(Qt.red, 3, Qt.DashLine)
        # self.default_pen.setCosmetic(True)
        # self.selected_pen.setCosmetic(True)

        self.setPen(self.default_pen)
        self.setData(TAG_KEY, set(tags))

        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        # self.setFlag(QGraphicsItem.ItemIsMovable, True)

    @override
    def paint(self, painter, option, widget=None):
        painter.setPen(self.selected_pen if self.isSelected() else self.default_pen)
        painter.drawPath(self.path())


class ScrollbarFreeCanvas(QGraphicsView):
    '''QGraphicsView with no scrollbars, supporting mouse and button zoom/pan.'''
    def __init__(self, scene: QGraphicsScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)

        # 1. Disable scrollbars completely
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 2. Required for manual matrix translation (panning without scrollbars)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        # Default mode: Drag a box to select items
        self.setDragMode(QGraphicsView.RubberBandDrag)

        self._is_panning = False
        self._pan_mode_active = False  # Toggled via UI button
        self._pan_start = None

    def zoom_all(self):
        # 1. Force the scene to recalculate its bounding rect
        self.scene().setSceneRect(self.scene().itemsBoundingRect())

        # 2. Defer fitInView until the event loop processes the geometry changes
        QTimer.singleShot(000, self.zoom_all_zoom)
        # QApplication.processEvents()
        # self.zoom_all_zoom()

    def zoom_all_zoom(self):
        pad = 8
        rect = self.scene().itemsBoundingRect()
        if not rect.isNull():
            rect.adjust(-pad, -pad, pad, pad)
            self.fitInView(rect, Qt.KeepAspectRatio)

    def set_pan_mode(self, enabled: bool):
        '''Toggle left-click panning mode from the UI panel.'''
        self._pan_mode_active = enabled
        if enabled:
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.RubberBandDrag)
            self.setCursor(Qt.ArrowCursor)

    def zoom_by(self, factor: float, anchor_pos=None):
        '''Zoom around a specific viewport point (or center if triggered by UI button).'''
        if anchor_pos is None:
            anchor_pos = self.viewport().rect().center()

        old_pos = self.mapToScene(anchor_pos)
        self.scale(factor, factor)
        new_pos = self.mapToScene(anchor_pos)

        # Shift view so the point under the cursor/center stays stationary
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

    def pan_by(self, dx: float, dy: float):
        '''Shift the canvas in screen pixels regardless of current zoom level.'''
        scale = self.transform().m11()
        self.translate(dx / scale, dy / scale)

    def reset_view(self):
        '''Reset zoom and pan back to origin.'''
        self.resetTransform()

    @override
    def wheelEvent(self, event):
        # zoom_factor = 1.15 if event.angleDelta().y() > 0 else (1 / 1.15)
        zoom_factor = 1.05 if event.angleDelta().y() > 0 else (1 / 1.05)
        self.zoom_by(zoom_factor, event.pos())

    @override
    def mousePressEvent(self, event):
        # Pan with Middle Mouse Button OR Left Click when Pan Mode is active
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self._pan_mode_active
        ):
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event):
        if self._is_panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.pan_by(delta.x(), delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.OpenHandCursor if self._pan_mode_active else Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class OutlinePathItem(QGraphicsPathItem):
    ''' simple outline paths '''
    @override
    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.pen().widthF(), 1))
        return stroker.createStroke(self.path())


class InteractivePathItem(OutlinePathItem):
    ''' outline paths with marker cross '''
    def __init__(self, path, marker_item):
        super().__init__(path)
        self.marker = marker_item
        self.setAcceptHoverEvents(True)
        # Make the clickable/hoverable area slightly thicker than the visible line
        self.setPen(QPen(QColor('#2b5b84'), 3))

    def get_closest_point(self, local_pos, samples=200):
        '''Finds the point on the QPainterPath closest to local_pos.'''
        path = self.path()
        closest_pt = QPointF()
        min_dist = float('inf')
        # coarse search along the path
        best_t = 0.0
        for i in range(samples + 1):
              t = i / samples
              pt = path.pointAtPercent(t)
              dist = math.hypot(pt.x() - local_pos.x(), pt.y() - local_pos.y())
              if dist < min_dist:
                    min_dist = dist
                    closest_pt = pt
                    best_t = t
        # fine search around the best_t for sub-pixel accuracy
        step = 1.0 / samples
        start_t = max(0.0, best_t - step)
        end_t = min(1.0, best_t + step)
        for i in range(21):
          t = start_t + (end_t - start_t) * (i / 20.0)
          pt = path.pointAtPercent(t)
          dist = math.hypot(pt.x() - local_pos.x(), pt.y() - local_pos.y())
          if dist < min_dist:
            min_dist = dist
            closest_pt = pt
        return closest_pt

    @override
    def hoverMoveEvent(self, event):
        ''' show and update the marker cross position '''
        closest_pt = self.get_closest_point(event.pos())
        self.marker.setPos(self.mapToScene(closest_pt))
        self.marker.setVisible(True)
        super().hoverMoveEvent(event)
        # print(f'X:{closest_pt.x():.2f}  Y:{closest_pt.y():.2f})')

    @override
    def hoverLeaveEvent(self, event):
        ''' hide the marker cross when the mouse leaves the line.'''
        self.marker.setVisible(False)
        super().hoverLeaveEvent(event)


class dxfGui(QFrame):
    def __init__(self):
        super().__init__()

        # self.setFrameShape(QFrame.StyledPanel)
        # self.setFrameShadow(QFrame.Raised)
        # self.setLineWidth(2)
        # self.setWindowTitle('PyQt5 Lines & Arcs: Scrollbar-Free Pan, Zoom & Tags')
        # self.resize(1000, 650)

        # Give the scene a massive virtual boundary so panning isn't restricted
        # self.scene = QGraphicsScene(-50000, -50000, 100000, 100000)
        # self.scene = QGraphicsScene(-5000, -5000, 100000, 100000)
        self.scene = QGraphicsScene(-5000, -5000, 10000, 10000)
        self.canvas = ScrollbarFreeCanvas(self.scene)
        self.cross_marker = self.create_marker_cross()
        # self.scene.addItem(self.cross_marker)

        self.D2P = dxf2PlasmaC()
        self.current_path = ''
        self.new_file = ''


        self.shape_color = Qt.black
        self.rapid_color = Qt.blue
        self.leadin_color = Qt.cyan
        self.cut_color_external  = Qt.red
        self.invalid_color  = Qt.magenta
        self.cut_color_internal = Qt.green
        self.selectedColor = Qt.yellow

        # self._populate_sample_items()
        self.icon_path = get_asset_path('assets/icons')
        self._setup_ui()

        self.import_dxf()


    def create_marker_cross(self, size=2, color=Qt.red):
        ''' create a marker cross '''
        pen = QPen(color, 2)
        pen.setCosmetic(True)
        cross_path = QPainterPath()
        cross_path.moveTo(-size, -size)
        cross_path.lineTo(size, size)
        cross_path.moveTo(-size, size)
        cross_path.lineTo(size, -size)
        cross_item = QGraphicsPathItem(cross_path)
        cross_item.setPen(pen)
        # cross_item.setZValue(10)  # render above the line
        cross_item.setVisible(False)
        return cross_item

    def import_dxf(self):
        file, _ = QFileDialog.getOpenFileName(
                    self,
                    'Open DXF File',
                    filter='DXF File (*.dxf);;Any File (*)',
                    directory=self.current_path)
        print(file)
        if file:
            self.setWindowTitle(f'dxf2PlasmaC     dxf file: {Path(file).name}')
            self.current_path = str(Path(file).parent)
            self.new_file = True
            self.D2P.open_dxf(file)
            # if self.error_check():
            #     return
            # self.create_layer_widgets()
            post = 'mm' if self.D2P.units == 'metric' else 'in'
            self.setWindowTitle(f'{self.windowTitle()}     Size: {self.D2P.size[0]}{post} x {self.D2P.size[1]}{post}')
            self.do_plot()

    def do_plot(self):

        # print(self.D2P.shape_points)

        self.plot(self.D2P.shape_points, 'shape', True)
        self.plot(self.D2P.cut_points, 'cut', False)

        self.canvas.zoom_all()
        # self.update()
        # if self.canvas.winfo_ismapped():
        #     if self.new_file:
        #         self.zoom_all()
        #         self.new_file = False
        #     else:
        #         self.canvas.scale('all', 0, 0, self.canvas_last['scale'], self.canvas_last['scale'])
        #         self.canvas.move('all', self.canvas_last['x'], self.canvas_last['y'])

    def paint(self, painter, option, _a):
        option.state = QStyle.State_None
        return super(MyClassName, self).paint(painter,option)

    def plot(self, points, mode:str='shape', clear:bool=False):
        ''' plot a job '''
        # the only difference between metric and inch are the origin pointer lengths
        spot = 10 if self.D2P.units == 'metric' else 0.02
        seq = 0
        # delete all existing objects
        if clear:
            self.scene.clear()
            self.scene.addItem(self.cross_marker)
            # self.mouse = (0, 0)
        # draw origin pointers once only
        if mode == 'shape':
            originPen = QPen(Qt.black, 2)
            originPen.setCosmetic(True)
            originBrush = QBrush(Qt.black)
            for angle in [45, 225]:
                origin = QGraphicsEllipseItem(0, 0, spot, spot)
                origin.setStartAngle(angle * 16)
                origin.setSpanAngle(90 * 16)
                origin.setPen(originPen)
                origin.setBrush(originBrush)
                self.scene.addItem(origin)
            outer = QGraphicsEllipseItem(0, 0, spot, spot)
            outer.setPen(originPen)
            self.scene.addItem(outer)
        # iterate through layers
        for layer in self.D2P.layers:
            if layer in self.D2P.ignored:
                continue
            # iterate through paths in cut sequence
            for point in self.D2P.sequences[layer]['cut']:
                 # shape was too small to offset
                if not points[layer][point]:
                    seq += 1
                    continue
                # iterate through segments
                for segment in points[layer][point]:
                    line = points[layer][point][segment]
                    if 'start' not in line:
                        continue
                    # get x and y, invert y
                    x1 = line['start'][0]
                    y1 = line['start'][1] * -1
                    x2 = line['end'][0]
                    y2 = line['end'][1] * -1

                    if segment < 4 or segment > len(points[layer][point]) - 3:
                        print(f'{mode} {point} {segment}:  {x1,y1}  {x2,y2}')

                    color = (self.shape_color if mode == 'shape' else
                             self.rapid_color if segment == 0 else
                             self.leadin_color if segment == 1 else
                             self.cut_color_external if self.D2P.sequences[layer]['external'][point] else
                             self.invalid_color if not self.D2P.sequences[layer]['lead-in'][point]['valid'] else
                             self.cut_color_internal)
                    seg_type = 'rapid' if segment == 0 else 'lead-in' if segment == 1 else 'feed'
                    pen = QPen(color, 2)
                    pen.setCosmetic(True)
                    # rapid segment
                    if segment == 0:
                        path = QPainterPath()
                        path.moveTo(x1, y1)
                        path.lineTo(x2, y2)
                        p = self.scene.addPath(path, pen)
                    # lead-in segment
                    elif segment == 1:
                        # arc lead-in
                        if 'cp' in line:
                            x = line['cp'][0]
                            y = line['cp'][1] * -1
                            r = line['r']
                            c = QPainterPath()
                            c.arcMoveTo(QRectF(x-r, y-r, r*2, r*2), ang)
                            c.arcTo(QRectF(x-r, y-r, r*2, r*2), ang, span)
                            path = InteractivePathItem(c, self.cross_marker) if mode == 'cut' else OutlinePathItem(c)
                            path.setPen(pen)
                            if mode == 'cut':
                                part.setFlag(QGraphicsItem.ItemIsSelectable, True)
                            self.scene.addItem(path)
                            p = path
                        # line lead-in
                        else:
                            l = QPainterPath()
                            l.moveTo(x1, y1)
                            l.lineTo(x2, y2)
                            path = InteractivePathItem(l, self.cross_marker) if mode == 'cut' else OutlinePathItem(l)
                            path.setPen(pen)
                            if mode == 'cut':
                                path.setFlag(QGraphicsItem.ItemIsSelectable, True)
                            self.scene.addItem(path)
                            p = path
                    # shape and cut segments
                    elif segment == 2:
                        # circle, there are no mor segments
                        if 'cp' in line:
                            x = line['cp'][0]
                            y = line['cp'][1] * -1
                            r = line['r']
                            c = QPainterPath()
                            c.addEllipse(x-r, y-r, r*2, r*2)
                            path = InteractivePathItem(c, self.cross_marker) if mode == 'cut' else OutlinePathItem(c)
                            path.setPen(pen)
                            if mode == 'cut':
                                path.setFlag(QGraphicsItem.ItemIsSelectable, True)
                            self.scene.addItem(path)
                            p = path
                        # line, this is the start
                        else:
                            l = QPainterPath()
                            l.moveTo(x1, y1)
                            # print(f'{segment}:{x1,y1}')                    # line end segments
                            # print(f'{segment}:{x2,y2}')                    # line end segments
                    else:
                        l.lineTo(x2, y2)
                    # last line segment
                    if segment == len(points[layer][point])-2 and segment > 3:
                        # print('last point', segment)
                        path = InteractivePathItem(l, self.cross_marker) if mode == 'cut' else OutlinePathItem(l)
                        path.setPen(pen)
                        if mode == 'cut':
                            path.setFlag(QGraphicsItem.ItemIsSelectable, True)
                        self.scene.addItem(path)
                        p = path
                    # segments 0, 1, and last segment require tags
                    if segment < 2 or segment == len(points[layer][point])-1:
                        p.setData(0, layer)
                        p.setData(1, mode)
                        p.setData(2, str(seq))
                        p.setData(3, str(line['seg']))
                        p.setData(4, seg_type)
                        p.setData(5, QColor(color).name())


#FIXME - fix the last half segment

#                         # if segment == 0:
#                         #     midx = (x1 + x2) / 2
#                         #     midy = (y1 + y2) / 2
#                         #     self.canvas.create_line(x1, y1, midx, midy, width=1, fill=fill, tags=tags, state=state, dash=(5, 5), arrow='last')
#                         #     self.canvas.create_line(midx, midy, x2, y2, width=1, fill=fill, tags=tags, state=state, dash=(5, 5))
#                         # else:
#                         #     self.canvas.create_line(x1, y1, x2, y2, width=1, fill=fill, tags=tags, state=state)

                seq += 1
        # if not self.show_rapids:
        #     self.canvas.itemconfig('rapid', state='hidden')
        # self.hide_paths_by_tag(4, 'lead-in')

    def hide_paths_by_tag(self, tag, target):
        if not self.scene:
            return
        for item in self.scene.items():
            if isinstance(item, QGraphicsPathItem) and item.data(tag) == target:
                    item.setVisible(False)

                        # p.setData(0, layer)
                        # p.setData(1, mode)
                        # p.setData(2, str(seq))
                        # p.setData(3, str(line['seg']))
                        # p.setData(4, seg_type)


    def _setup_ui(self):
        # main_layout = QHBoxLayout(self)
        # main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout = QGridLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Left side: Canvas
        # main_layout.addWidget(self.canvas, stretch=1)
        main_layout.addWidget(self.canvas, 1, 1)

        toolbar = QHBoxLayout()
        icon_size = 32

        btn_import_dxf = QToolButton()
        btn_import_dxf.setFixedSize(QSize(icon_size, icon_size))
        btn_import_dxf.setIcon(QIcon(f'{self.icon_path}/import_dxf.png'))
        btn_import_dxf.setIconSize(QSize(icon_size, icon_size))
        btn_import_dxf.setAutoRaise(True)
        btn_import_dxf.setToolTip('Import DXF file')
        toolbar.addWidget(btn_import_dxf)

        btn_export_gcode = QToolButton()
        btn_export_gcode.setFixedSize(QSize(icon_size, icon_size))
        btn_export_gcode.setIcon(QIcon(f'{self.icon_path}/export_gcode.png'))
        btn_export_gcode.setIconSize(QSize(icon_size, icon_size))
        btn_export_gcode.setToolTip('Export Gcode file')
        toolbar.addWidget(btn_export_gcode)

        btn_reload = QToolButton()
        btn_reload.setFixedSize(QSize(icon_size, icon_size))
        btn_reload.setIcon(QIcon(f'{self.icon_path}/reload.png'))
        btn_reload.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_reload)

        btn_open_project = QToolButton()
        btn_open_project.setFixedSize(QSize(icon_size, icon_size))
        btn_open_project.setIcon(QIcon(f'{self.icon_path}/open_project.png'))
        btn_open_project.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_open_project)

        btn_save_project = QToolButton()
        btn_save_project.setFixedSize(QSize(icon_size, icon_size))
        btn_save_project.setIcon(QIcon(f'{self.icon_path}/save_project.png'))
        btn_save_project.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_save_project)

        btn_settings = QToolButton()
        btn_settings.setFixedSize(QSize(icon_size, icon_size))
        btn_settings.setIcon(QIcon(f'{self.icon_path}/settings.png'))
        btn_settings.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_settings)

        btn_info = QToolButton()
        btn_info.setFixedSize(QSize(icon_size, icon_size))
        btn_info.setIcon(QIcon(f'{self.icon_path}/info.png'))
        btn_info.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_info)

        btn_zoom_all = QToolButton()
        btn_zoom_all.setFixedSize(QSize(icon_size, icon_size))
        btn_zoom_all.setIcon(QIcon(f'{self.icon_path}/zoom_all.png'))
        btn_zoom_all.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_zoom_all)

        btn_zoom_in = QToolButton()
        btn_zoom_in.setFixedSize(QSize(icon_size, icon_size))
        btn_zoom_in.setIcon(QIcon(f'{self.icon_path}/zoom_in.png'))
        btn_zoom_in.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_zoom_in)

        btn_zoom_out = QToolButton()
        btn_zoom_out.setFixedSize(QSize(icon_size, icon_size))
        btn_zoom_out.setIcon(QIcon(f'{self.icon_path}/zoom_out.png'))
        btn_zoom_out.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_zoom_out)

        btn_pan_left = QToolButton()
        btn_pan_left.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_left.setIcon(QIcon(f'{self.icon_path}/pan_left.png'))
        btn_pan_left.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_pan_left)

        btn_pan_right = QToolButton()
        btn_pan_right.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_right.setIcon(QIcon(f'{self.icon_path}/pan_right.png'))
        btn_pan_right.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_pan_right)

        btn_pan_up = QToolButton()
        btn_pan_up.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_up.setIcon(QIcon(f'{self.icon_path}/pan_up.png'))
        btn_pan_up.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_pan_up)

        btn_pan_down = QToolButton()
        btn_pan_down.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_down.setIcon(QIcon(f'{self.icon_path}/pan_down.png'))
        btn_pan_down.setIconSize(QSize(icon_size, icon_size))
        toolbar.addWidget(btn_pan_down)

        toolbar_spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        toolbar.addItem(toolbar_spacer)

        main_layout.addLayout(toolbar, 0, 0, 1, 2)

        # Right side: Control Panel
        panel = QWidget()
        panel.setFixedWidth(240)
        panel_layout = QVBoxLayout(panel)

        # --- Interaction Mode Group ---
        mode_group = QGroupBox('Mouse Mode')
        mode_layout = QVBoxLayout(mode_group)

        self.btn_pan_mode = QPushButton('Hand Pan Mode: OFF')
        self.btn_pan_mode.setCheckable(True)
        self.btn_pan_mode.toggled.connect(self._toggle_pan_mode)
        mode_layout.addWidget(self.btn_pan_mode)

        hint_label = QLabel('Tip: Middle-click drag always pans.')
        hint_label.setStyleSheet('color: gray; font-size: 11px;')
        mode_layout.addWidget(hint_label)
        panel_layout.addWidget(mode_group)

        # --- Zoom Controls Group ---
        zoom_group = QGroupBox('Zoom')
        zoom_layout = QHBoxLayout(zoom_group)

        btn_zoom_in = QPushButton('Zoom +')
        btn_zoom_out = QPushButton('Zoom -')
        btn_zoom_all = QPushButton('Zoom All')

        btn_zoom_in.clicked.connect(lambda: self.canvas.zoom_by(1.25))
        btn_zoom_out.clicked.connect(lambda: self.canvas.zoom_by(0.8))
        btn_zoom_all.clicked.connect(self.canvas.zoom_all)

        zoom_layout.addWidget(btn_zoom_in)
        zoom_layout.addWidget(btn_zoom_out)
        zoom_layout.addWidget(btn_zoom_all)
        panel_layout.addWidget(zoom_group)

        # --- Directional Pan Pad Group ---
        pan_group = QGroupBox('Pan Controls')
        pan_grid = QGridLayout(pan_group)
        step = 50  # pixels per click

        btn_up = QPushButton('▲')
        btn_down = QPushButton('▼')
        btn_left = QPushButton('◀')
        btn_right = QPushButton('▶')

        btn_up.clicked.connect(lambda: self.canvas.pan_by(0, step))
        btn_down.clicked.connect(lambda: self.canvas.pan_by(0, -step))
        btn_left.clicked.connect(lambda: self.canvas.pan_by(step, 0))
        btn_right.clicked.connect(lambda: self.canvas.pan_by(-step, 0))

        pan_grid.addWidget(btn_up, 0, 1)
        pan_grid.addWidget(btn_left, 1, 0)
        pan_grid.addWidget(btn_right, 1, 2)
        pan_grid.addWidget(btn_down, 2, 1)
        panel_layout.addWidget(pan_group)

        # --- Selected Item Tags Group ---
        tag_group = QGroupBox('Selected Tags')
        tag_layout = QVBoxLayout(tag_group)
        self.lbl_tags = QLabel('None selected')
        self.lbl_tags.setWordWrap(True)
        tag_layout.addWidget(self.lbl_tags)
        panel_layout.addWidget(tag_group)

        panel_layout.addStretch()
        main_layout.addWidget(panel, 1, 0)
        # self.setCentralWidget(central_widget)

        self.scene.selectionChanged.connect(self._update_selected_tags)

    def _toggle_pan_mode(self, checked: bool):
        self.btn_pan_mode.setText(f'Hand Pan Mode: {'ON' if checked else 'OFF'}')
        self.canvas.set_pan_mode(checked)

    def _update_selected_tags(self):
        selected = self.scene.selectedItems()
        if not selected:
            self.lbl_tags.setText('None selected')
            return
        tags = [selected[0].data(n) for n in [0,1,2,3,4,5]]
        self.lbl_tags.setText(', '.join(tags))

        # self.path_item = InteractivePathItem(selected[0], self.cross_marker)
        # self.scene.addItem(self.path_item)
        # print(selected[0])#.option())
        # sPen = QPen(self.selectedColor, 1)
        # # sPen.setCosmetic(True)
        # selected[0].setPen(sPen)
        # selected[0].setSelected(False)

# if __name__ == '__main__':
#     app = QApplication(sys.argv)
#     window = MainWindow()
#     window.show()
#     sys.exit(app.exec_())
