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
    QCursor,
    QIcon,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSpacerItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .dxf_to_plasmac import dxf2PlasmaC

TAG_LAYER    = 0
TAG_MODE     = 1
TAG_SEQUENCE = 2
TAG_SEGMENT  = 3
TAG_TYPE     = 4
TAG_COLOR    = 5

def get_asset_path(relative_path: str) -> str:
    ''' resolves paths for local pixi development and compiled pyinstaller bundles '''
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class Canvas(QGraphicsView):
    ''' QGraphicsView with no scrollbars, with mouse and button zoom/pan '''
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
        self.setDragMode(QGraphicsView.NoDrag)

        self._is_panning = False
        self._pan_mode_active = True
        self._pan_start = None

    def zoom_all(self):
        ''' zoom to fit with a delay to ensure processing is complete '''
        self.scene().setSceneRect(self.scene().itemsBoundingRect())
        QTimer.singleShot(0, self.zoom_all_zoom)

    def zoom_all_zoom(self):
        ''' complete the zoom '''
        pad = 8
        rect = self.scene().itemsBoundingRect()
        if not rect.isNull():
            rect.adjust(-pad, -pad, pad, pad)
            self.fitInView(rect, Qt.KeepAspectRatio)

    def zoom_step(self, factor: float, anchor_pos=None):
        ''' zoom  by mouse wheel or button steps'''
        if anchor_pos is None:
            anchor_pos = self.viewport().rect().center()
        old_pos = self.mapToScene(anchor_pos)
        self.scale(factor, factor)
        new_pos = self.mapToScene(anchor_pos)
        # Shift view so the point under the cursor/center stays stationary
        delta = new_pos - old_pos
        self.translate(delta.x(), delta.y())

    def pan_step(self, dx: float, dy: float):
        ''' pan by right mouse drag or buttons'''
        scale = self.transform().m11()
        self.translate(dx / scale, dy / scale)

    @override
    def wheelEvent(self, event):
        ''' zoom by wheel '''
        zoom_factor = 1.05 if event.angleDelta().y() > 0 else (1 / 1.05)
        self.zoom_step(zoom_factor, event.pos())

    @override
    def mousePressEvent(self, event):
        ''' start pan by right mouse '''
        if event.button() == Qt.RightButton:
            self._is_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.OpenHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    @override
    def mouseMoveEvent(self, event):
        ''' pan by mouse drag '''
        if self._is_panning and self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.pan_step(delta.x(), delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event):
        ''' end pan by mouse '''
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class OutlinePath(QGraphicsPathItem):
    ''' simple outline path for original shape and rapids '''
    @override
    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.pen().widthF(), 1))
        return stroker.createStroke(self.path())


class OutlineCutPath(OutlinePath):
    ''' outline paths with marker cross for cuts except rapids '''
    def __init__(self, path, marker_item):
        super().__init__(path)
        self.marker = marker_item
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(QColor('#2b5b84'), 3))

    def get_closest_point(self, local_pos, samples=200):
        ''' find closect point on the path to the mouse '''
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

    @override
    def hoverLeaveEvent(self, event):
        ''' hide the marker cross when the mouse leaves the line.'''
        self.marker.setVisible(False)
        super().hoverLeaveEvent(event)


class dxfGui(QFrame):
    def __init__(self, material_file=''):
        super().__init__()
        self.scene = QGraphicsScene(-5000, -5000, 10000, 10000)
        self.scene.selectionChanged.connect(self.item_selected)
        self.canvas = Canvas(self.scene)
        self.cross_marker = None

        self.current_path = ''
        self.new_file = ''

        self.material_file = material_file
        # print('material file =', self.material_file)

        self.shape_color = Qt.black
        self.rapid_color = Qt.blue
        self.leadin_color = Qt.cyan
        self.cut_color_external  = Qt.red
        self.cut_color_internal = Qt.green
        self.invalid_color  = Qt.magenta
        self.selectedColor = Qt.yellow

        self.selected_item = ''

        self.icon_path = get_asset_path(os.path.join('assets', 'icons'))

        self.D2P = dxf2PlasmaC()
        # self.D2P.lead_type = 'arc'

        self._setup_ui()

        # self.canvas.setContextMenuPolicy(Qt.CustomContextMenu)
        # self.canvas.customContextMenuRequested.connect(self.menu_popup)

        # self.import_dxf()


    def import_dxf(self):
        ''' load and process a dxf file '''
        file, _ = QFileDialog.getOpenFileName(
                self,
                'Open DXF File',
                filter='DXF File (*.dxf);;Any File (*)',
                directory=self.current_path)
        if file:
            self.status.setText(f'dxf file: {Path(file).name}')
            self.current_path = str(Path(file).parent)
            self.new_file = True
            self.D2P.open_dxf(file)
            if self.error_check():
                return
            self.create_layer_widgets()
            post = 'mm' if self.D2P.units == 'metric' else 'in'
            self.status.setText(f'dxf file: {Path(file).name}     Size: {self.D2P.size[0]}{post} x {self.D2P.size[1]}{post}')
            self.do_plot()

    def export_gcode(self, _event):
        path = os.path.join(self.current_path, Path(self.D2P.loaded_file).stem)
        file, _ = QFileDialog.getSaveFileName(
                self,
                'Save GCode File',
                path,
                filter='GCode File (*.ngc);;Any File (*)')
        if file:
            self.D2P.write_gcode(file)
            self.error_check()

    def open_project(self, _event):
        file, _ = QFileDialog.getOpenFileName(
                self,
                'Open Project',
                filter='Project File (*.d2p);;Any File(*)',
                directory=self.current_path)
        if file:
            self.status.setText(f'project file: {Path(file).name}')
            self.current_path = str(Path(file).parent)
            self.new_file = True
            self.selected_item = ''
            self.D2P.open_project(file)
            if self.error_check():
                return
            self.create_layer_widgets()
            post = 'mm' if self.D2P.units == 'metric' else 'in'
            self.status.setText(f'project file: {Path(file).name}     Size: {self.D2P.size[0]}{post} x {self.D2P.size[1]}{post}')
            self.do_plot()

    def save_project(self, _event):
        path = os.path.join(self.current_path, Path(self.D2P.loaded_file).stem)
        file, _ = QFileDialog.getSaveFileName(
                self,
                'Save Project',
                path,
                filter='Project File (*.d2p);;(Any File (*)')
        if file:
            self.current_path = str(Path(file).parent)
            self.D2P.save_project(file)
            self.error_check()

    def do_plot(self):
        ''' plot the job '''
        self.plot(self.D2P.shape_points, 'shape', True)
        self.plot(self.D2P.cut_points, 'cut', False)
        self.canvas.zoom_all()
#FIXME we need to track the scaling so we don't change the view on edits
        # self.update()
        # if self.canvas.winfo_ismapped():
        #     if self.new_file:
        #         self.zoom_all()
        #         self.new_file = False
        #     else:
        #         self.canvas.scale('all', 0, 0, self.canvas_last['scale'], self.canvas_last['scale'])
        #         self.canvas.move('all', self.canvas_last['x'], self.canvas_last['y'])

    # def paint(self, painter, option, _a):
    #     option.state = QStyle.State_None
    #     return super(MyClassName, self).paint(painter,option)

    def plot(self, points, mode:str='shape', clear:bool=False):
        ''' plot a shape or a cut '''
        # the only difference between metric and inch is the origin pointer size
        spot = 1 if self.D2P.units == 'metric' else 0.08
        seq = 0
        # keep pyright quiet
        path = ''
        item = ''
        # delete all existing objects
        if clear:
            self.scene.clear()
            self.cross_marker = self.create_marker_cross()
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
                    color = (self.shape_color if mode == 'shape' else
                             self.rapid_color if segment == 0 else
                             self.leadin_color if segment == 1 else
                             self.cut_color_external if self.D2P.sequences[layer]['external'][point] else
                             self.invalid_color if not self.D2P.sequences[layer]['lead-in'][point]['valid'] else
                             self.cut_color_internal)
                    seg_type = 'rapid' if segment == 0 else 'lead-in' if segment == 1 else 'feed' if mode == 'cut' else 'shape'
                    pen = QPen(color, 2)
                    pen.setCosmetic(True)
                    # rapid segment
                    if segment == 0:
#                        print(f'segment {segment}   rapid')
                        path = QPainterPath()
                        path.moveTo(x1, y1)
                        path.lineTo(x2, y2)
                        item = self.scene.addPath(path, pen)
                        # add an arrow to center point
                        xc = (x1 + x2) / 2
                        yc = (y1 + y2) / 2
                        ang = math.atan2(y2-y1, x2-x1)
                        l = 2 if self.D2P.units == 'metric' else 0.08
                        xs = xc + l * math.cos(ang + math.radians(150))
                        ys = yc + l * math.sin(ang + math.radians(150))
                        xe = xc + l * math.cos(ang + math.radians(210))
                        ye = yc + l * math.sin(ang + math.radians(210))
                        path = QPainterPath()
                        path.moveTo(xs, ys)
                        path.lineTo(xc, yc)
                        path.lineTo(xe, ye)
                    # arc lead-in segment
                    elif segment == 1 and 'cp' in line:
#                        print(f'segment {segment}   arc lead-in')
                        x = line['cp'][0]
                        y = line['cp'][1] * -1
                        r = line['r']
                        ang = line['sa']
                        span = line['e']
                        path = QPainterPath()
                        path.arcMoveTo(QRectF(x-r, y-r, r*2, r*2), ang)
                        path.arcTo(QRectF(x-r, y-r, r*2, r*2), ang, span)
                    # circle
                    elif 'cp' in line:
#                        print(f'segment {segment}   circle')
                        x = line['cp'][0]
                        y = line['cp'][1] * -1
                        r = line['r']
                        path = QPainterPath()
                        path.addEllipse(x-r, y-r, r*2, r*2)
                    # line
                    else:
#                        print(f'segment {segment}   line')
                        path = QPainterPath()
                        path.moveTo(x1, y1)
                        path.lineTo(x2, y2)
                    # segment 0 (rapid) is not selectable
                    if segment == 0:
                        item = self.scene.addPath(path, pen)
                    else:
                        item = OutlineCutPath(path, self.cross_marker) if mode == 'cut' else OutlinePath(path)
                        item.setPen(pen)
                        if mode == 'cut':
                            item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                        self.scene.addItem(item)
                    # tag all segments
                    item.setData(TAG_LAYER, layer)
                    item.setData(TAG_MODE, mode)
                    item.setData(TAG_SEQUENCE, str(seq))
                    item.setData(TAG_SEGMENT, str(line['seg']))
                    item.setData(TAG_TYPE, seg_type)
                    item.setData(TAG_COLOR, QColor(color).name())


#*********************************************************************************************************
# single segment doesn't work because we cannot reliably select a specific point...
                    # # shape and cut segments
                    # elif segment == 2:
                    #     # circle, there are no more segments
                    #     if 'cp' in line:
                    #         x = line['cp'][0]
                    #         y = line['cp'][1] * -1
                    #         r = line['r']
                    #         path = QPainterPath()
                    #         path.addEllipse(x-r, y-r, r*2, r*2)
                    #         item = OutlineCutPath(path, self.cross_marker) if mode == 'cut' else OutlinePath(path)
                    #         item.setPen(pen)
                    #         if mode == 'cut':
                    #             item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                    #         self.scene.addItem(item)
                    #     # line, this is the start
                    #     else:
                    #         path = QPainterPath()
                    #         path.moveTo(x1, y1)
                    #         path.lineTo(x2, y2)
                    # # remaingin segments except last
                    # elif segment < len(points[layer][point])-1:
                    #     path.lineTo(x2, y2)
                    # # last line segment
                    # if segment == len(points[layer][point])-1 and segment > 3:
                    #     path.lineTo(x2, y2)
                    #     item = OutlineCutPath(path, self.cross_marker) if mode == 'cut' else OutlinePath(path)
                    #     item.setPen(pen)
                    #     if mode == 'cut':
                    #         item.setFlag(QGraphicsItem.ItemIsSelectable, True)
                    #     self.scene.addItem(item)
                    # # segments 0, 1, and last segment require tags
                    # if segment < 2 or segment == len(points[layer][point])-1:
                    #     item.setData(TAG_LAYER, layer)
                    #     item.setData(TAG_MODE, mode)
                    #     item.setData(TAG_SEQUENCE, str(seq))
                    #     item.setData(TAG_SEGMENT, str(line['seg']))
                    #     item.setData(TAG_TYPE, seg_type)
                    #     item.setData(TAG_COLOR, QColor(color).name())
#*********************************************************************************************************


                seq += 1
        if mode == 'cut':
            if not self.show_rapids.isChecked():
                self.hide_paths_by_tag(TAG_TYPE, 'rapid', False)
            for layer in self.D2P.ignored:
                self.hide_paths_by_tag(TAG_LAYER, layer, False)

    def hide_paths_by_tag(self, tag, target, visible):
        ''' show/hide paths by tag '''
        if not self.scene:
            return
        for item in self.scene.items():
            if isinstance(item, QGraphicsPathItem) and item.data(tag) == target:
                    item.setVisible(visible)

    def show_rapids_changed(self, state):
        ''' show/hide rapid moves '''
        self.hide_paths_by_tag(TAG_TYPE, 'rapid', state)

    def show_lead_ins_changed(self, state):
        ''' show/hide lead-ins '''
        self.hide_paths_by_tag(TAG_TYPE, 'lead-in', state)

    def show_feeds_changed(self, state):
        ''' show/hide cut moves '''
        self.hide_paths_by_tag(TAG_TYPE, 'feed', state)

    def show_shapes_changed(self, state):
        ''' show/hide original shapes '''
        self.hide_paths_by_tag(TAG_MODE, 'shape', state)

    def toggle_layer_visibility(self, state, layer):
        ''' show/hide layers by name '''
        self.hide_paths_by_tag(TAG_LAYER, layer, state)
        if state:
            self.D2P.ignored.remove(layer)
        else:
            self.D2P.ignored.append(layer)

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

    def create_layer_widgets(self):
        ''' create layer checkboxes in the sidebar '''
        self.clear_layout(self.layer_layout)
        for layer in self.D2P.layers:
            check = QCheckBox(layer)
            if layer not in self.D2P.ignored:
                check.setChecked(True)
            check.stateChanged.connect(lambda s, l=layer: self.toggle_layer_visibility(s, l))
            self.layer_layout.addWidget(check)

    def clear_layout(self, layout):
        ''' remove layer checkboxes from the sidebar '''
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

    def load_material_file(self):
        ''' load materials form material file '''
        self.D2P.load_materials(self.material_file)
        if self.error_check():
            return
        self.material_select.addItems(self.D2P.material_names)
        self.show_material()
        if self.D2P.loaded_file:
            self.do_plot()

    def show_material(self):
        ''' display material values in the sidebar'''
        # self.material_var.set(f'{self.D2P.material['nu']}:  {self.D2P.material['na']}')
        self.kerf_width.setValue(float(self.D2P.material['kw']))
        self.cut_speed.setValue(float(self.D2P.material['fr']))
        self.cut_height.setValue(float(self.D2P.material['ch']))
        self.pierce_height.setValue(float(self.D2P.material['ph']))
        self.pierce_delay.setValue(float(self.D2P.material['pd']))

    def select_material(self, material):
        ''' selected a material '''
        self.D2P.select_material(material.split(':')[0].strip())
        self.show_material()
        if self.D2P.loaded_file:
            self.do_plot()

    def kerf_changed(self, value):
        ''' kerf width changed, redraw if required '''
        try:
            self.D2P.kerf = float(value)
            if self.D2P.loaded_file:
                self.D2P.get_points('cut')
                self.error_check()
                self.do_plot()
        except ValueError:
            pass

    def get_path_coord_from_global(self, global_pos) -> QPointF:
        view = self.canvas
        path = self.selected_item
        viewport_pos = view.viewport().mapFromGlobal(global_pos)
        scene_pos = view.mapToScene(viewport_pos)
        path_pos = path.mapFromScene(scene_pos)
        return path_pos

    def change_sequence(self, cut, seq, layer):
        # add 1 here so user doesn't see cut sequence #0
        mini = min(self.D2P.sequences[layer]['cut']) + 1
        maxi = max(self.D2P.sequences[layer]['cut']) + 1
        new_seq, ok = QInputDialog.getInt(self,
                'Cut Sequence',
                f'Select a new cut position\nfrom {mini} to {maxi}',
                seq + 1,
                mini,
                maxi,
                1)
        if ok and new_seq != seq + 1:
            self.D2P.change_cut_sequence(layer, cut, new_seq)
            # self.error_check()
            # self.do_plot()

    def change_start_segment(self, layer, cut, segment, global_pos):
        data = self.D2P.cut_points[layer][cut][int(segment)]
        # line
        if 'cp' not in data:
            self.D2P.change_start_segment(layer, cut, int(segment))
        # circle
        else:
            pos = self.get_path_coord_from_global(global_pos)
            ang = math.atan2(-pos.y()-data['cp'][1], pos.x()-data['cp'][0])
            self.D2P.change_start_angle(layer, cut, math.degrees(ang))

    def lead_in_length(self, cut, radius, external_cut, layer):
        maxi = radius if radius and radius < self.D2P.small_hole and not external_cut else 10
        length, ok = QInputDialog.getDouble(self,
                'Lead-in Length',
                f'Enter a new lead-in length\nfom 0 to {maxi}',
                self.D2P.sequences[layer]['lead-in'][cut]['length'],
                0,
                maxi,
                2)
        if ok:
            self.D2P.change_lead_in_length(layer, cut, length)

    def lead_in_angle(self, cut, layer):
        angle, ok = QInputDialog.getInt(self,
                'Lead-in Angle',
                'Enter lead-in angle:',
                self.D2P.sequences[layer]['lead-in'][cut]['angle'],
                10,
                90,
                 1)
        if ok:
            self.D2P.change_lead_in_angle(layer, cut, angle)

    def error_check(self):
        ''' display warnings and or errors '''
        if self.D2P.warning:
            QMessageBox.warning(self, 'Warning', '\n'.join(self.D2P.warning))
        if self.D2P.error:
            QMessageBox.critical(self, 'Error', self.D2P.error)
            return True
        return False

    def menu_popup(self, position, title, options) ->str:
        option = ''
        menu = QMenu(self)
        menu.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        menu.setWindowModality(Qt.ApplicationModal)

        def answer(text):
            nonlocal option
            nonlocal menu
            option = text
            menu.close()

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        title_action = QWidgetAction(menu)
        title_action.setDefaultWidget(title_label)
        menu.addAction(title_action)
        menu.addSeparator()
        for opt in options:
            if opt:
                action = QAction(opt, self)
                action.triggered.connect(lambda checked=False, a=opt: answer(a))
                if opt == 'Cancel':
                    menu.addSeparator()
                menu.addAction(action)
        menu.exec_(position)
        return option

    def show_option_menu(self, position):
        ''' display the context menu at the mouse cursor position '''
        if self.selected_item:
            seq = int(self.selected_item.data(TAG_SEQUENCE))
            layer = self.selected_item.data(TAG_LAYER)
            cut = self.D2P.sequences[layer]['cut'][seq]
            path = self.D2P.paths[layer][self.D2P.sequences[layer]['cut'][seq]]
            segment = self.selected_item.data(TAG_SEGMENT)
            external_cut = self.D2P.sequences[layer]['external'][self.D2P.sequences[layer]['cut'][seq]]
            radius = path.get('r', None) if isinstance(path, dict) else None
            opts = []
            if segment == 0:
                return
            title = f'Cut: #{seq + 1}'
            opts.append('Change Cut Sequence')
            if isinstance(path, dict) or path.is_closed:
                opts.append('External \u2192 Internal' if self.D2P.sequences[layer]['external'][cut] else 'Internal \u2192 External')
                opts.append('Set As Start Point')
                if radius and radius > self.D2P.small_hole / 2 or external_cut or not radius:
                    opts.append('Line \u2192 Arc' if self.D2P.sequences[layer]['lead-in'][cut]['type'] == 'line' else 'Arc \u2192 Line')
                opts.append('Change Lead-in Length')
                if self.D2P.sequences[layer]['lead-in'][cut]['type'] == 'line':
                    opts.append('Change Lead-in Angle')
            opts.append('Cancel')
            option = self.menu_popup(position, title, opts)#, color)
            valid = True
            match option:
                case 'Change Cut Sequence':
                    # self.color_selected(self.canvas.type(self.selected_item), False)
                    self.change_sequence(cut, seq, layer)
                case 'Internal \u2192 External' | 'External \u2192 Internal':
                    self.D2P.toggle_side(layer, cut)
                case 'Set As Start Point':
                    self.change_start_segment(layer, cut, segment, position)
                case 'Line \u2192 Arc' | 'Arc \u2192 Line':
                    self.D2P.toggle_lead(layer, cut)
                case 'Change Lead-in Length':
                    self.lead_in_length(cut, radius, external_cut, layer)
                case 'Change Lead-in Angle':
                    self.lead_in_angle(cut, layer)
                case _:
                    valid = False
            if valid:
                self.error_check()
                QTimer.singleShot(100, self.do_plot)
            self.selected_item = ''

    def item_selected(self):
        if self.scene.selectedItems():
            self.selected_item = self.scene.selectedItems()[0]
            self.show_option_menu(QCursor.pos())
        else:
            self.selected_item = ''

    def _setup_ui(self):
        ''' create the ui '''
        # layout
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        # canvas at row 1 column 1
        layout.addWidget(self.canvas, 1, 1)
        # toolbar at row 0
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        icon_size = 32
        pan_step = 50  # pixels per click
        # file
        btn_import_dxf = QToolButton()
        btn_import_dxf.setFixedSize(QSize(icon_size, icon_size))
        btn_import_dxf.setIcon(QIcon(os.path.join(self.icon_path, 'import_dxf.png')))
        btn_import_dxf.setIconSize(QSize(icon_size, icon_size))
        btn_import_dxf.setAutoRaise(True)
        btn_import_dxf.setToolTip('Import DXF file')
        btn_import_dxf.clicked.connect(self.import_dxf)
        toolbar.addWidget(btn_import_dxf)
        btn_export_gcode = QToolButton()
        btn_export_gcode.setFixedSize(QSize(icon_size, icon_size))
        btn_export_gcode.setIcon(QIcon(os.path.join(self.icon_path, 'export_gcode.png')))
        btn_export_gcode.setIconSize(QSize(icon_size, icon_size))
        btn_export_gcode.setToolTip('Export Gcode file')
        btn_export_gcode.clicked.connect(self.export_gcode)
        toolbar.addWidget(btn_export_gcode)
        # reload
        btn_reload = QToolButton()
        btn_reload.setFixedSize(QSize(icon_size, icon_size))
        btn_reload.setIcon(QIcon(os.path.join(self.icon_path, 'reload.png')))
        btn_reload.setIconSize(QSize(icon_size, icon_size))
        btn_reload.setToolTip('Reload DXF file or project')
        toolbar.addWidget(btn_reload)
        # project
        btn_open_project = QToolButton()
        btn_open_project.setFixedSize(QSize(icon_size, icon_size))
        btn_open_project.setIcon(QIcon(os.path.join(self.icon_path, 'open_project.png')))
        btn_open_project.setIconSize(QSize(icon_size, icon_size))
        btn_open_project.setToolTip('Open a saved project')
        btn_open_project.clicked.connect(self.open_project)
        toolbar.addWidget(btn_open_project)
        btn_save_project = QToolButton()
        btn_save_project.setFixedSize(QSize(icon_size, icon_size))
        btn_save_project.setIcon(QIcon(os.path.join(self.icon_path, 'save_project.png')))
        btn_save_project.setIconSize(QSize(icon_size, icon_size))
        btn_save_project.setToolTip('Save a project')
        btn_save_project.clicked.connect(self.save_project)
        toolbar.addWidget(btn_save_project)
        # settings
        btn_settings = QToolButton()
        btn_settings.setFixedSize(QSize(icon_size, icon_size))
        btn_settings.setIcon(QIcon(os.path.join(self.icon_path, 'settings.png')))
        btn_settings.setIconSize(QSize(icon_size, icon_size))
        btn_settings.setToolTip('Settings')
        toolbar.addWidget(btn_settings)
        # info
        btn_info = QToolButton()
        btn_info.setFixedSize(QSize(icon_size, icon_size))
        btn_info.setIcon(QIcon(os.path.join(self.icon_path, 'info.png')))
        btn_info.setIconSize(QSize(icon_size, icon_size))
        btn_info.setToolTip('Information')
        toolbar.addWidget(btn_info)
        # zoom
        btn_zoom_all = QToolButton()
        btn_zoom_all.setFixedSize(QSize(icon_size, icon_size))
        btn_zoom_all.setIcon(QIcon(os.path.join(self.icon_path, 'zoom_all.png')))
        btn_zoom_all.setIconSize(QSize(icon_size, icon_size))
        btn_zoom_all.clicked.connect(self.canvas.zoom_all)
        btn_zoom_all.setToolTip('Zoom to fit')
        toolbar.addWidget(btn_zoom_all)
        btn_zoom_in = QToolButton()
        btn_zoom_in.setFixedSize(QSize(icon_size, icon_size))
        btn_zoom_in.setIcon(QIcon(os.path.join(self.icon_path, 'zoom_in.png')))
        btn_zoom_in.setIconSize(QSize(icon_size, icon_size))
        btn_zoom_in.clicked.connect(lambda: self.canvas.zoom_step(1.25))
        btn_zoom_in.setToolTip('Zoom in')
        toolbar.addWidget(btn_zoom_in)
        btn_zoom_out = QToolButton()
        btn_zoom_out.setFixedSize(QSize(icon_size, icon_size))
        btn_zoom_out.setIcon(QIcon(os.path.join(self.icon_path, 'zoom_out.png')))
        btn_zoom_out.setIconSize(QSize(icon_size, icon_size))
        btn_zoom_out.clicked.connect(lambda: self.canvas.zoom_step(0.8))
        btn_zoom_out.setToolTip('Zoom out')
        toolbar.addWidget(btn_zoom_out)
        # pan
        btn_pan_left = QToolButton()
        btn_pan_left.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_left.setIcon(QIcon(os.path.join(self.icon_path, 'pan_left.png')))
        btn_pan_left.setIconSize(QSize(icon_size, icon_size))
        btn_pan_left.clicked.connect(lambda: self.canvas.pan_step(pan_step, 0))
        btn_pan_left.setToolTip('Pan left')
        toolbar.addWidget(btn_pan_left)
        btn_pan_right = QToolButton()
        btn_pan_right.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_right.setIcon(QIcon(os.path.join(self.icon_path, 'pan_right.png')))
        btn_pan_right.setIconSize(QSize(icon_size, icon_size))
        btn_pan_right.clicked.connect(lambda: self.canvas.pan_step(-pan_step, 0))
        btn_pan_right.setToolTip('Pan right')
        toolbar.addWidget(btn_pan_right)
        btn_pan_up = QToolButton()
        btn_pan_up.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_up.setIcon(QIcon(os.path.join(self.icon_path, 'pan_up.png')))
        btn_pan_up.setIconSize(QSize(icon_size, icon_size))
        btn_pan_up.clicked.connect(lambda: self.canvas.pan_step(0, pan_step))
        btn_pan_up.setToolTip('Pan up')
        toolbar.addWidget(btn_pan_up)
        btn_pan_down = QToolButton()
        btn_pan_down.setFixedSize(QSize(icon_size, icon_size))
        btn_pan_down.setIcon(QIcon(os.path.join(self.icon_path, 'pan_down.png')))
        btn_pan_down.setIconSize(QSize(icon_size, icon_size))
        btn_pan_down.clicked.connect(lambda: self.canvas.pan_step(0, -pan_step))
        btn_pan_down.setToolTip('Pan down')
        toolbar.addWidget(btn_pan_down)
        toolbar_spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        toolbar.addItem(toolbar_spacer)
        layout.addLayout(toolbar, 0, 0, 1, 2)
        # sidebar at row 1 column 0
        sidebar_container = QWidget()
        sidebar_container.setFixedWidth(180)
        sidebar = QVBoxLayout(sidebar_container)
        sidebar.setContentsMargins(0, 0, 0, 0)
        # layers
        layer_group = QGroupBox('Layers')
        self.layer_layout = QVBoxLayout(layer_group)
        self.layer_layout.setContentsMargins(0, 0, 0, 0)
        sidebar.addWidget(layer_group)
        # spacer
        sidebar_spacer1 = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar.addItem(sidebar_spacer1)
        # view
        view_group = QGroupBox('View')
        view_layout = QVBoxLayout(view_group)
        view_layout.setContentsMargins(0, 0, 0, 0)
        self.show_rapids = QCheckBox('Rapid Segments')
        self.show_rapids.setChecked(True)
        self.show_rapids.stateChanged.connect(self.show_rapids_changed)
        view_layout.addWidget(self.show_rapids)
        self.show_lead_ins = QCheckBox('Lead-in Segments')
        self.show_lead_ins.setChecked(True)
        self.show_lead_ins.stateChanged.connect(self.show_lead_ins_changed)
        view_layout.addWidget(self.show_lead_ins)
        self.show_feeds = QCheckBox('Feed Segments')
        self.show_feeds.setChecked(True)
        self.show_feeds.stateChanged.connect(self.show_feeds_changed)
        view_layout.addWidget(self.show_feeds)
        self.show_shapes = QCheckBox('Shapes')
        self.show_shapes.setChecked(True)
        self.show_shapes.stateChanged.connect(self.show_shapes_changed)
        view_layout.addWidget(self.show_shapes)
        sidebar.addWidget(view_group)
        # spacer
        sidebar_spacer2 = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Expanding)
        sidebar.addItem(sidebar_spacer2)
        # materials
        material_group = QGroupBox('Material')
        material_layout = QGridLayout(material_group)
        material_layout.setContentsMargins(0, 0, 0, 0)
        kerf_width_L = QLabel('Kerf Width')
        kerf_width_L.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        material_layout.addWidget(kerf_width_L, 0, 0)
        self.kerf_width = QDoubleSpinBox()
        self.kerf_width.setRange(0, 5)
        self.kerf_width.valueChanged.connect(self.kerf_changed)
        material_layout.addWidget(self.kerf_width, 0, 1)
        cut_speed_L = QLabel('CutSpeed')
        cut_speed_L.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        material_layout.addWidget(cut_speed_L, 1, 0)
        self.cut_speed = QDoubleSpinBox()
        self.cut_speed.setRange(0, 10000)
        material_layout.addWidget(self.cut_speed, 1, 1)
        cut_height_L = QLabel('Cut Height')
        cut_height_L.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        material_layout.addWidget(cut_height_L, 2, 0)
        self.cut_height = QDoubleSpinBox()
        self.cut_height.setRange(0, 10)
        material_layout.addWidget(self.cut_height, 2, 1)
        pierce_height_L = QLabel('Pierce Height')
        pierce_height_L.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        material_layout.addWidget(pierce_height_L, 3, 0)
        self.pierce_height = QDoubleSpinBox()
        self.pierce_height.setRange(0, 10)
        material_layout.addWidget(self.pierce_height, 3, 1)
        pierce_delay_L = QLabel('Pierce Delay')
        pierce_delay_L.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        material_layout.addWidget(pierce_delay_L, 4, 0)
        self.pierce_delay = QDoubleSpinBox()
        self.pierce_delay.setRange(0, 10)
        material_layout.addWidget(self.pierce_delay, 4, 1)
        sidebar.addWidget(material_group)
        layout.addWidget(sidebar_container, 1, 0)
        # statusbar at row 2 for material and status
        statusbar_container = QWidget()
        statusbar_container.setFixedHeight(24)
        statusbar = QHBoxLayout(statusbar_container)
        statusbar.setContentsMargins(0, 0, 0, 0)
        statusbar.setSpacing(8)
        material_L = QLabel('Material')
        material_L.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        material_L.setFixedWidth(84)
        statusbar.addWidget(material_L)
        self.material_select = QComboBox()
        self.material_select.setFixedWidth(200)
        self.material_select.currentTextChanged.connect(self.select_material)
        statusbar.addWidget(self.material_select)
        statusbar_spacer = QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Expanding)
        statusbar.addItem(statusbar_spacer)
        self.status = QLabel('')
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        statusbar.addWidget(self.status)
        statusbar.addSpacing(8)
        layout.addWidget(statusbar_container, 2, 0, 1, 2)

        # sidebar is complete, setup materials
        if self.material_file:
            self.load_material_file()
        else:
            if self.D2P.units == 'metric':
                self.kerf_width.setValue(1)
                self.cut_speed.setValue(1000)
                self.cut_height.setValue(1)
                self.pierce_height.setValue(3)
            else:
                self.kerf_width.setValue(0.04)
                self.cut_speed.setValue(250)
                self.cut_height.setValue(0.04)
                self.pierce_height.setValue(0.12)
            self.pierce_delay.setValue(1)
            self.material_select.addItem('Default')


    # def in_bounds(self, x, b1, b2):
    #     low, high = min(abs(b1), abs(b2)), max(abs(b1), abs(b2))
    #     tol = 1e-9
    #     return ((low <= abs(x) <= high) or
    #             math.isclose(abs(x), low, abs_tol=tol) or
    #             math.isclose(abs(x), high, abs_tol=tol))



    # tag testing
    # def _update_selected_tags(self):
#     def item_selected(self):
#         # print('_update_selected_tags')
#         selected = self.scene.selectedItems()
#         if not selected:
#             self.selected_item = ''
#             # self.lbl_tags.setText('None selected')
#             return
#         # print(f'QCursor.pos(): {QCursor.pos()}')
#         tags = [selected[0].data(n) for n in [0,1,2,3,4,5]]
#         for t in tags:
#             print(f'tag {t} {type(t)}')
#         # self.lbl_tags.setText(', '.join(tags))
#         # # bob = self.menu_popup(QCursor.pos())
#         # # print(f'bob: {bob}')
#
#         # if self.scene.selectedItems():
#         self.selected_item = self.scene.selectedItems()[0]
#         self.show_option_menu(QCursor.pos())

        # self.path_item = OutlineCutPath(selected[0], self.cross_marker)
        # self.scene.addItem(self.path_item)
        # print(selected[0])#.option())
        # sPen = QPen(self.selectedColor, 1)
        # # sPen.setCosmetic(True)
        # selected[0].setPen(sPen)
        # selected[0].setSelected(False)
        # self.selected_item = ''
