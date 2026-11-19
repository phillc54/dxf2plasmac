import sys
from typing import override

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
)

# Custom key constant for storing tags
TAG_KEY = 0


class SelectablePathItem(QGraphicsPathItem):
    """A custom line/arc item that supports tags and visual selection feedback."""
    def __init__(self, path: QPainterPath, tags: list[str], color=Qt.blue):
        super().__init__(path)
        self.default_pen = QPen(color, 1)
        self.selected_pen = QPen(Qt.red, 2, Qt.DashLine)

        self.setPen(self.default_pen)
        self.setData(TAG_KEY, set(tags))  # Store tags as a Python set

        # Enable selection and movement
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)

    @override
    def paint(self, painter, option, widget=None):
        # Change appearance automatically when selected
        if self.isSelected():
            painter.setPen(self.selected_pen)
        else:
            painter.setPen(self.default_pen)
        painter.drawPath(self.path())


class InteractiveCanvas(QGraphicsView):
    """A QGraphicsView supporting mouse-wheel zoom and drag panning."""
    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)

        # Zoom towards the mouse cursor
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        # Enable rubber-band drag selection by default
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self._is_panning = False
        self._pan_start = None
        self.current_scale = 1

    @override
    def wheelEvent(self, event):
        """Zoom in and out with the mouse wheel."""
        zoom_factor = 1.05
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
            self.current_scale *= zoom_factor
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)
            self.current_scale /= zoom_factor
        print(self.current_scale)

    @override
    def mousePressEvent(self, event):
        """Enable panning with Middle Mouse Button."""
        # if event.button() == Qt.MiddleButton:
        if event.button() == Qt.RightButton:
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
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event):  # type: ignore[override]
        # if event.button() == Qt.MiddleButton:
        if event.button() == Qt.RightButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)


def main():
    app = QApplication(sys.argv)
    scene = QGraphicsScene(-500, -500, 1000, 1000)

    # 1. Create a Straight Line
    line_path = QPainterPath()
    line_path.moveTo(-150, -50)
    line_path.lineTo(150, -50)
    line_item = SelectablePathItem(line_path, tags=["wall", "straight"], color=QColor("#2b5c8f"))
    scene.addItem(line_item)

    # 2. Create an Arc
    arc_path = QPainterPath()
    bounding_rect = QRectF(-100, 0, 200, 200)  # Rectangle defining the arc's ellipse
    arc_path.arcMoveTo(bounding_rect, 0)        # Start at 0 degrees (3 o'clock)
    arc_path.arcTo(bounding_rect, 0, 180)       # Sweep 180 degrees counter-clockwise
    arc_item = SelectablePathItem(arc_path, tags=["door_swing", "arc"], color=QColor("#2e8b57"))
    scene.addItem(arc_item)

    # Print tags whenever selection changes
    def on_selection_changed():
        for item in scene.selectedItems():
            tags = item.data(TAG_KEY)
            print(f"Selected item with tags: {tags}")

    scene.selectionChanged.connect(on_selection_changed)

    view = InteractiveCanvas(scene)
    view.setWindowTitle("PyQt5 Lines & Arcs: Select, Tag, Zoom & Pan")
    view.resize(800, 600)
    view.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
