"""
Loading Overlay — полупрозрачный оверлей с анимированным спиннером.

Используется во всех виджетах, которые загружают данные с сервера.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen
import math


class SpinnerWidget(QWidget):
    """Анимированное колесо загрузки (12 точек по кругу)"""

    def __init__(self, parent=None, size=48, dot_count=12):
        super().__init__(parent)
        self._size = size
        self._dot_count = dot_count
        self._current = 0
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.setInterval(80)

    def start(self):
        self._current = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _rotate(self):
        self._current = (self._current + 1) % self._dot_count
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self._size / 2
        cy = self._size / 2
        radius = self._size / 2 - 8
        dot_radius = 3.5

        for i in range(self._dot_count):
            angle = 2 * math.pi * i / self._dot_count - math.pi / 2
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)

            # Точки затухают от текущей позиции
            distance = (self._current - i) % self._dot_count
            opacity = max(0.15, 1.0 - distance * 0.08)

            color = QColor("#0369a1")
            color.setAlphaF(opacity)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(int(x - dot_radius), int(y - dot_radius),
                                int(dot_radius * 2), int(dot_radius * 2))

        painter.end()


class LoadingOverlay(QWidget):
    """Полупрозрачный оверлей поверх родительского виджета"""

    def __init__(self, parent=None, text="Загрузка данных..."):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.spinner = SpinnerWidget(self)
        layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        self.label = QLabel(text)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "color: #0369a1; font-size: 13px; font-weight: 600; "
            "background: transparent; padding-top: 8px;"
        )
        layout.addWidget(self.label)

        self.hide()

    def show_overlay(self, text="Загрузка данных..."):
        """Показать оверлей поверх родителя"""
        self.label.setText(text)
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.spinner.start()

    def hide_overlay(self):
        """Скрыть оверлей"""
        self.spinner.stop()
        self.hide()

    def paintEvent(self, event):
        """Полупрозрачный белый фон"""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(255, 255, 255, 210))
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)


class ApiWorker(QThread):
    """
    Фоновый поток для вызова API.

    Принимает callable (api_func) и аргументы.
    По завершении — сигнал finished с результатом.
    """
    finished = pyqtSignal(dict)

    def __init__(self, api_func, *args, **kwargs):
        super().__init__()
        self._api_func = api_func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._api_func(*self._args, **self._kwargs)
        except Exception as e:
            result = {"success": False, "error": str(e)}
        self.finished.emit(result)
