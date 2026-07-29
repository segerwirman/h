import math
from PyQt6.QtCore import Qt, QTimer, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget, QApplication

class MiniReactor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(150, 150)
        
        # Position in bottom right corner
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 170, screen.height() - 170)
        
        self.angle = 0
        self.pulse = 0
        self.pulse_dir = 1
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30)

    def update_animation(self):
        self.angle = (self.angle + 2) % 360
        self.pulse += 5 * self.pulse_dir
        if self.pulse > 100:
            self.pulse_dir = -1
        elif self.pulse < 0:
            self.pulse_dir = 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        cx = self.width() / 2
        cy = self.height() / 2
        radius = min(cx, cy) - 10
        
        # Glow
        grad = QRadialGradient(QPointF(cx, cy), radius)
        glow_alpha = 100 + int(self.pulse * 0.5)
        grad.setColorAt(0, QColor(0, 150, 255, glow_alpha))
        grad.setColorAt(1, QColor(0, 20, 50, 0))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        
        # Outer Ring
        pen = QPen(QColor(0, 150, 255, 200), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius * 0.9, radius * 0.9)
        
        # Rotating segments
        painter.translate(cx, cy)
        painter.rotate(self.angle)
        pen.setWidth(4)
        painter.setPen(pen)
        for i in range(8):
            painter.drawLine(int(radius * 0.6), 0, int(radius * 0.8), 0)
            painter.rotate(45)
            
        painter.rotate(-self.angle * 2) # Counter rotate inner
        for i in range(3):
            painter.drawArc(
                int(-radius * 0.4), int(-radius * 0.4), 
                int(radius * 0.8), int(radius * 0.8), 
                0, 16 * 60
            )
            painter.rotate(120)

        # Center triangle
        painter.rotate(self.angle * 1.5)
        painter.setBrush(QColor(0, 150, 255, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        pts = [
            QPointF(0, -radius * 0.2),
            QPointF(-radius * 0.17, radius * 0.1),
            QPointF(radius * 0.17, radius * 0.1)
        ]
        painter.drawPolygon(pts)
