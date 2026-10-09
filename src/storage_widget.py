"""
Sphaira-style storage capacity bars widget.
Two rows (NAND, microSD) drawn the way Kefir Hub draws its status bars: a fixed
label column, bars of one and the same width, a fixed value column. Before an
install the planned usage of the selected packages is projected into the free
space (red when it does not fit), the hovered row's package in amber at the head
of the segment; during an install the remaining bytes of the active package.
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QFontMetrics

from .utility_functions import format_size

# the widest value either row can show; both rows reserve this column, so the
# bars never change length when the text does (Hub: value_col_w template).
VALUE_TEMPLATE = "+000.0 MB / 000.0 MB / 000.0 GB"
LABEL_TEMPLATE = "microSD"

SEG_FITS = QColor(33, 150, 243)      # planned usage that fits (Hub HIGHLIGHT_1 blue)
SEG_NO_FIT = QColor(230, 60, 60)     # planned usage that does not fit
SEG_FOCUS = QColor(255, 200, 60)     # hovered package / remaining bytes of the active one


def projection_geometry(bar_w: int, total: int, free: int, used_fill_w: int, planned: int, focus: int):
    """Segment widths the Hub uses for a projection: (seg_w, focus_w, fits).
    seg_w is clamped to the free part of the bar, focus_w to the segment."""
    if total <= 0 or planned <= 0:
        return 0, 0, True
    seg_w = min(bar_w - used_fill_w, max(2, int(bar_w * planned / total)))
    focus_w = min(seg_w, max(2, int(bar_w * focus / total))) if focus > 0 else 0
    fits = free > 0 and planned <= free
    return max(0, seg_w), max(0, focus_w), fits


class StorageBarRow(QWidget):
    """Single storage bar row: [Label] [Bar] [Value]."""

    def __init__(self, label_text: str, parent=None):
        super().__init__(parent)
        self.label_text = label_text
        self.free_bytes = 0
        self.total_bytes = 0
        self.highlight_bytes = 0  # active install: size of the package being installed
        self.focus_bytes = 0      # active install: bytes written so far
        self.planned_bytes = 0    # projection: everything queued for this drive
        self.planned_focus = 0    # projection: the hovered package's part of it
        self.setFixedHeight(16)

    def set_storage(self, free_bytes: int, total_bytes: int):
        self.free_bytes = free_bytes
        self.total_bytes = total_bytes
        self.update()

    def set_install_progress(self, focus_bytes: int, highlight_bytes: int):
        self.focus_bytes = min(focus_bytes, highlight_bytes)
        self.highlight_bytes = highlight_bytes
        self.update()

    def clear_install_progress(self):
        self.focus_bytes = 0
        self.highlight_bytes = 0
        self.update()

    def set_projection(self, planned_bytes: int, focus_bytes: int):
        self.planned_bytes = planned_bytes
        self.planned_focus = min(focus_bytes, planned_bytes)
        self.update()

    def clear_projection(self):
        self.planned_bytes = 0
        self.planned_focus = 0
        self.update()

    @property
    def installing(self) -> bool:
        return self.highlight_bytes > 0

    @property
    def projecting(self) -> bool:
        return not self.installing and self.planned_bytes > 0

    def get_value_text(self) -> str:
        """Hub formats: install "+written / size / free", projection "+focus / planned / free", idle "free"."""
        if self.total_bytes <= 0:
            return "--"
        if self.installing:
            return f"+{format_size(self.focus_bytes)} / {format_size(self.highlight_bytes)} / {format_size(self.free_bytes)}"
        if self.projecting:
            return f"+{format_size(self.planned_focus)} / {format_size(self.planned_bytes)} / {format_size(self.free_bytes)}"
        return f"{format_size(self.free_bytes)} free"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        label_w = QFontMetrics(font).horizontalAdvance(LABEL_TEMPLATE)

        is_dark = self.palette().text().color().lightness() > 128
        label_col = QColor("#9e9e9e") if is_dark else QColor("#555555")
        val_col = QColor("#cccccc") if is_dark else QColor("#333333")
        track_col = QColor(60, 60, 60, 200) if is_dark else QColor(210, 210, 210, 220)
        if self.installing or self.projecting:
            val_col = SEG_FITS

        painter.setPen(label_col)
        painter.drawText(0, 0, label_w, h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self.label_text)

        font_plain = painter.font()
        font_plain.setBold(False)
        painter.setFont(font_plain)
        val_w = painter.fontMetrics().horizontalAdvance(VALUE_TEMPLATE)
        val_x = w - val_w
        painter.setPen(val_col)
        painter.drawText(val_x, 0, val_w, h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.get_value_text())

        # the bar sits between the two fixed columns, so both rows get the same width.
        bar_x = label_w + 8
        bar_w = max(0, val_x - bar_x - 12)
        bar_h = 7
        bar_y = int((h - bar_h) / 2)
        if bar_w <= 0:
            return

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_col)
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 3, 3)
        if self.total_bytes <= 0:
            return

        used_bytes = max(0, self.total_bytes - self.free_bytes)
        used_ratio = min(1.0, used_bytes / self.total_bytes)
        fill_w = int(bar_w * used_ratio)
        if used_ratio > 0.90:
            fill_col = QColor(230, 60, 60)
        elif used_ratio > 0.75:
            fill_col = QColor(230, 180, 60)
        else:
            fill_col = QColor(90, 200, 120)

        painter.save()
        clip_path = QPainterPath()
        clip_path.addRoundedRect(float(bar_x), float(bar_y), float(bar_w), float(bar_h), 3.0, 3.0)
        painter.setClipPath(clip_path)

        if fill_w > 0:
            painter.setBrush(fill_col)
            painter.drawRect(bar_x, bar_y, fill_w, bar_h)

        if self.installing:
            # remaining bytes of the active package shrink toward 0 as bytes are written.
            rem_bytes = max(0, self.highlight_bytes - self.focus_bytes)
            if rem_bytes > 0:
                seg_w = min(bar_w - fill_w, max(2, int(bar_w * rem_bytes / self.total_bytes)))
                if seg_w > 0:
                    painter.setBrush(SEG_FOCUS)
                    painter.drawRect(bar_x + fill_w, bar_y, seg_w, bar_h)
        elif self.projecting:
            seg_w, focus_w, fits = projection_geometry(
                bar_w, self.total_bytes, self.free_bytes, fill_w, self.planned_bytes, self.planned_focus)
            if seg_w > 0:
                painter.setBrush(SEG_FITS if fits else SEG_NO_FIT)
                painter.drawRect(bar_x + fill_w, bar_y, seg_w, bar_h)
            if focus_w > 0:
                painter.setBrush(SEG_FOCUS)
                painter.drawRect(bar_x + fill_w, bar_y, focus_w, bar_h)

        painter.restore()


class SwitchStorageWidget(QWidget):
    """Two stacked storage capacity bars for NAND and microSD matching Sphaira's UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.nand_row = StorageBarRow("NAND", self)
        self.sd_row = StorageBarRow("microSD", self)

        layout.addWidget(self.nand_row)
        layout.addWidget(self.sd_row)

        self.setFixedHeight(34)
        self.setMinimumWidth(280)
        self._update_tooltips()

    def set_storage_info(self, nand_free: int, nand_total: int, sd_free: int, sd_total: int):
        self.nand_row.set_storage(nand_free, nand_total)
        self.sd_row.set_storage(sd_free, sd_total)
        self._update_tooltips()

    def set_install_progress(self, target: str, focus_bytes: int, highlight_bytes: int):
        """target is 'sd' or 'nand'."""
        if target == 'sd':
            self.sd_row.set_install_progress(focus_bytes, highlight_bytes)
            self.nand_row.clear_install_progress()
        elif target == 'nand':
            self.nand_row.set_install_progress(focus_bytes, highlight_bytes)
            self.sd_row.clear_install_progress()
        else:
            self.clear_install_progress()
        self._update_tooltips()

    def clear_install_progress(self):
        self.sd_row.clear_install_progress()
        self.nand_row.clear_install_progress()
        self._update_tooltips()

    def set_projection(self, nand_bytes: int, sd_bytes: int, nand_focus: int = 0, sd_focus: int = 0):
        """Planned usage of the selected packages per drive (the Hub's SetStorageProjection)."""
        self.nand_row.set_projection(nand_bytes, nand_focus)
        self.sd_row.set_projection(sd_bytes, sd_focus)
        self._update_tooltips()

    def clear_projection(self):
        self.nand_row.clear_projection()
        self.sd_row.clear_projection()
        self._update_tooltips()

    def _update_tooltips(self):
        if self.sd_row.total_bytes > 0:
            lines = []
            for row in (self.sd_row, self.nand_row):
                used = max(0, row.total_bytes - row.free_bytes)
                pct = int(used / row.total_bytes * 100) if row.total_bytes > 0 else 0
                lines.append(f"{row.label_text}: {format_size(row.free_bytes)} free of {format_size(row.total_bytes)} ({pct}% used)")
                if row.installing:
                    lines.append(f"Installing to {row.label_text}: {format_size(row.focus_bytes)} / {format_size(row.highlight_bytes)}")
                elif row.projecting:
                    fits = row.planned_bytes <= row.free_bytes
                    lines.append(f"Selected packages for {row.label_text}: {format_size(row.planned_bytes)}" + ("" if fits else " — does not fit"))
            tip = "\n".join(lines)
        else:
            tip = "Waiting for console storage info..."
        self.setToolTip(tip)
