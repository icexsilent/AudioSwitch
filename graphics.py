"""
Desenho vetorial de ícones de áudio, periféricos e baterias com QPainter.
Desenhado em canvas lógico 24x24 com antialiasing, mantendo nitidez em qualquer escala de DPI (100%, 125%, 150%...).
Inspirado no visual do BateriaBT.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

DEVICE_KINDS = (
    "headset",
    "inear",
    "wireless",
    "speaker",
    "monitor",
    "microphone",
    "keyboard",
    "mouse",
    "gamepad",
    "generic",
)

KIND_LABELS = {
    "headset": "Headset (Over-ear)",
    "inear": "Fone In-Ear (Intra-auricular)",
    "wireless": "Headset Sem Fio",
    "speaker": "Caixa de Som / Alto-falante",
    "monitor": "Monitor / TV",
    "microphone": "Microfone",
    "generic": "Áudio Genérico",
}

_icon_cache = {}


def _dot(path: QPainterPath, x: float, y: float):
    path.moveTo(x, y)
    path.lineTo(x + 0.01, y)


def _line(path: QPainterPath, *points):
    path.moveTo(*points[0])
    for pt in points[1:]:
        path.lineTo(*pt)


def _polygon(path: QPainterPath, *points):
    _line(path, *points)
    path.closeSubpath()


def _device_paths(kind: str, style: str = "outline"):
    cache_key = (kind, style)
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]

    stroke, fill = QPainterPath(), QPainterPath()
    filled = style == "filled"
    minimal = style == "minimal"

    if kind == "headset":
        if filled:
            stroke.moveTo(4.5, 14.0)
            stroke.lineTo(4.5, 11.0)
            stroke.arcTo(QRectF(4.5, 3.5, 15.0, 15.0), 180, -180)
            stroke.lineTo(19.5, 14.0)
            fill.addRoundedRect(QRectF(2.0, 11.0, 5.5, 9.5), 2.6, 2.6)
            fill.addRoundedRect(QRectF(16.5, 11.0, 5.5, 9.5), 2.6, 2.6)
        elif minimal:
            stroke.arcMoveTo(QRectF(4.0, 4.0, 16.0, 16.0), 200)
            stroke.arcTo(QRectF(4.0, 4.0, 16.0, 16.0), 200, -220)
            stroke.addRoundedRect(QRectF(3.0, 12.0, 3.2, 8.0), 1.6, 1.6)
            stroke.addRoundedRect(QRectF(17.8, 12.0, 3.2, 8.0), 1.6, 1.6)
        else:  # outline (padrão BateriaBT)
            stroke.moveTo(4.8, 14.0)
            stroke.lineTo(4.8, 11.5)
            stroke.arcTo(QRectF(4.8, 4.3, 14.4, 14.4), 180, -180)
            stroke.lineTo(19.2, 14.0)
            fill.addRoundedRect(QRectF(3.0, 12.6, 4.8, 8.2), 2.0, 2.0)
            fill.addRoundedRect(QRectF(16.2, 12.6, 4.8, 8.2), 2.0, 2.0)

    elif kind == "wireless":
        # Headset + ondas sem fio no topo/centro
        stroke.moveTo(4.8, 14.2)
        stroke.lineTo(4.8, 11.8)
        stroke.arcTo(QRectF(4.8, 4.6, 14.4, 14.4), 180, -180)
        stroke.lineTo(19.2, 14.2)
        if filled:
            fill.addRoundedRect(QRectF(2.4, 12.0, 5.0, 8.8), 2.3, 2.3)
            fill.addRoundedRect(QRectF(16.6, 12.0, 5.0, 8.8), 2.3, 2.3)
        elif minimal:
            stroke.addRoundedRect(QRectF(3.0, 12.4, 3.4, 7.8), 1.6, 1.6)
            stroke.addRoundedRect(QRectF(17.6, 12.4, 3.4, 7.8), 1.6, 1.6)
        else:
            fill.addRoundedRect(QRectF(3.0, 12.8, 4.6, 8.0), 2.0, 2.0)
            fill.addRoundedRect(QRectF(16.4, 12.8, 4.6, 8.0), 2.0, 2.0)
        # Pequeno arco de sinal wireless no centro
        stroke.arcMoveTo(QRectF(9.2, 9.0, 5.6, 5.6), 45)
        stroke.arcTo(QRectF(9.2, 9.0, 5.6, 5.6), 45, 90)
        fill.addEllipse(QPointF(12.0, 13.5), 1.1, 1.1)

    elif kind == "inear":
        # Fone intra-auricular (IEM / KZ EDX Pro): duas cápsulas angulares + cabo em Y
        if filled:
            fill.addRoundedRect(QRectF(3.2, 4.5, 6.8, 6.8), 3.2, 3.2)
            fill.addRoundedRect(QRectF(14.0, 4.5, 6.8, 6.8), 3.2, 3.2)
            fill.addEllipse(QPointF(8.8, 6.4), 1.7, 1.7)
            fill.addEllipse(QPointF(15.2, 6.4), 1.7, 1.7)
        else:
            stroke.addRoundedRect(QRectF(3.6, 4.8, 6.2, 6.2), 3.0, 3.0)
            stroke.addRoundedRect(QRectF(14.2, 4.8, 6.2, 6.2), 3.0, 3.0)
            if not minimal:
                fill.addEllipse(QPointF(6.7, 7.9), 1.1, 1.1)
                fill.addEllipse(QPointF(17.3, 7.9), 1.1, 1.1)
        # Cabos descendo em Y até o conector P2
        stroke.moveTo(6.7, 11.0)
        stroke.cubicTo(6.7, 15.5, 12.0, 15.5, 12.0, 18.5)
        stroke.moveTo(17.3, 11.0)
        stroke.cubicTo(17.3, 15.5, 12.0, 15.5, 12.0, 18.5)
        _line(stroke, (12.0, 18.0), (12.0, 21.5))

    elif kind == "speaker":
        if filled:
            fill.setFillRule(Qt.OddEvenFill)
            fill.addRoundedRect(QRectF(5.0, 2.0, 14.0, 20.0), 3.0, 3.0)
            fill.addEllipse(QPointF(12.0, 6.8), 1.8, 1.8)
            fill.addEllipse(QPointF(12.0, 14.8), 4.2, 4.2)
        elif minimal:
            stroke.addRoundedRect(QRectF(6.0, 3.0, 12.0, 18.0), 2.5, 2.5)
            stroke.addEllipse(QPointF(12.0, 14.0), 3.0, 3.0)
        else:
            stroke.addRoundedRect(QRectF(6.0, 2.5, 12.0, 19.0), 3.0, 3.0)
            stroke.addEllipse(QPointF(12.0, 14.6), 3.3, 3.3)
            fill.addEllipse(QPointF(12.0, 7.4), 1.2, 1.2)

    elif kind == "monitor":
        if filled:
            fill.setFillRule(Qt.OddEvenFill)
            fill.addRoundedRect(QRectF(2.0, 4.0, 20.0, 14.0), 2.2, 2.2)
            fill.addRoundedRect(QRectF(3.9, 5.9, 16.2, 10.2), 0.6, 0.6)
        else:
            stroke.addRoundedRect(QRectF(2.5, 4.5, 19.0, 13.0), 2.0, 2.0)
        _line(stroke, (7.8, 21.0), (16.2, 21.0))
        if not minimal:
            _line(stroke, (12.0, 17.5), (12.0, 21.0))

    elif kind == "microphone":
        if filled:
            fill.addRoundedRect(QRectF(8.4, 2.0, 7.2, 12.5), 3.6, 3.6)
        else:
            stroke.addRoundedRect(QRectF(8.8, 2.5, 6.4, 11.5), 3.2, 3.2)
        stroke.moveTo(5.2, 11.5)
        stroke.cubicTo(5.2, 20.0, 18.8, 20.0, 18.8, 11.5)
        _line(stroke, (12.0, 17.8), (12.0, 21.5))
        if not minimal:
            _line(stroke, (8.6, 21.5), (15.4, 21.5))

    else:
        # Ícone de ondas sonoras (alto-falante lateral)
        if filled:
            _polygon(fill, (3.5, 9.5), (7.5, 9.5), (12.5, 5.0), (12.5, 19.0), (7.5, 14.5), (3.5, 14.5))
        else:
            _polygon(stroke, (3.5, 9.5), (7.5, 9.5), (12.5, 5.0), (12.5, 19.0), (7.5, 14.5), (3.5, 14.5))
        stroke.arcMoveTo(QRectF(11.5, 8.0, 6.0, 8.0), -45)
        stroke.arcTo(QRectF(11.5, 8.0, 6.0, 8.0), -45, 90)
        if not minimal:
            stroke.arcMoveTo(QRectF(10.5, 4.5, 10.5, 15.0), -45)
            stroke.arcTo(QRectF(10.5, 4.5, 10.5, 15.0), -45, 90)

    _icon_cache[cache_key] = (stroke, fill)
    return stroke, fill


def _begin_box(p: QPainter, rect: QRectF, box: float = 24.0) -> float:
    s = min(rect.width(), rect.height()) / box
    p.translate(rect.x() + (rect.width() - box * s) / 2, rect.y() + (rect.height() - box * s) / 2)
    p.scale(s, s)
    return s


def _pen(color, width: float) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def draw_device_icon(p: QPainter, rect: QRectF, kind: str, color, weight: float = 1.85, style: str = "outline"):
    stroke, fill = _device_paths(kind if kind in DEVICE_KINDS else "generic", style=style)
    p.save()
    _begin_box(p, rect)
    p.setPen(_pen(color, weight))
    p.setBrush(Qt.NoBrush)
    if not stroke.isEmpty():
        p.drawPath(stroke)
    if not fill.isEmpty():
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPath(fill)
    p.restore()


_BOLT = ((6.2, 0.0), (0.6, 9.3), (4.7, 9.3), (3.8, 16.0), (9.4, 6.4), (5.3, 6.4))


def bolt_path(rect: QRectF) -> QPainterPath:
    s = min(rect.width() / 10.0, rect.height() / 16.0)
    ox = rect.x() + (rect.width() - 10.0 * s) / 2
    oy = rect.y() + (rect.height() - 16.0 * s) / 2
    path = QPainterPath()
    path.moveTo(ox + _BOLT[0][0] * s, oy + _BOLT[0][1] * s)
    for x, y in _BOLT[1:]:
        path.lineTo(ox + x * s, oy + y * s)
    path.closeSubpath()
    return path


def draw_bolt(p: QPainter, rect: QRectF, fill, outline=None, outline_width: float = 1.2):
    path = bolt_path(rect)
    p.save()
    if outline is not None:
        pen = _pen(outline, outline_width * 2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(fill))
    p.drawPath(path)
    p.restore()


def draw_battery(
    p: QPainter,
    rect: QRectF,
    level,
    fill,
    outline,
    track=None,
    charging: bool = False,
    phase: float = 0.0,
    bolt_fill: str = "#FFFFFF",
    bolt_outline=None,
):
    """Pilha horizontal idêntica à do BateriaBT."""
    h = rect.height()
    nub_w = max(1.6, h * 0.16)
    gap = max(0.8, h * 0.07)
    body = QRectF(rect.x(), rect.y(), rect.width() - nub_w - gap, h)
    stroke = max(1.0, h * 0.1)
    radius = h * 0.27

    p.save()
    outline_c = QColor(outline)
    p.setPen(QPen(outline_c, stroke))
    p.setBrush(QColor(track) if track is not None else Qt.NoBrush)
    half = stroke / 2
    p.drawRoundedRect(body.adjusted(half, half, -half, -half), radius, radius)

    nub_h = h * 0.4
    p.setPen(Qt.NoPen)
    p.setBrush(outline_c)
    p.drawRoundedRect(
        QRectF(body.right() + gap, rect.center().y() - nub_h / 2, nub_w, nub_h),
        nub_w * 0.45,
        nub_w * 0.45,
    )

    pad = stroke + max(0.8, h * 0.08)
    inner = body.adjusted(pad, pad, -pad, -pad)
    if level is not None and fill is not None and inner.width() > 0:
        level = max(0, min(100, int(level)))
        width = inner.width() * level / 100.0
        if level > 0:
            width = max(width, min(inner.width(), max(1.3, h * 0.13)))
        fill_rect = QRectF(inner.x(), inner.y(), width, inner.height())
        inner_radius = max(0.6, radius * 0.5)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(fill_rect, inner_radius, inner_radius)
        if charging and width > 2:
            band = max(inner.width() * 0.5, 4.0)
            x = inner.x() - band + (inner.width() + band) * (phase % 1.0)
            grad = QLinearGradient(x, 0, x + band, 0)
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, QColor(255, 255, 255, 110))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setClipRect(fill_rect)
            p.setBrush(grad)
            p.drawRect(fill_rect)
            p.setClipping(False)

    if charging:
        bh = h * 0.92
        bw = bh * 10.0 / 16.0
        b_rect = QRectF(body.center().x() - bw / 2, body.center().y() - bh / 2, bw, bh)
        draw_bolt(p, b_rect, bolt_fill, bolt_outline, max(0.9, h * 0.08))

    p.restore()
