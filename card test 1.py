import math
import os
import random
import sys

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# ------------------------
# Assets & deck
# ------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARD_BACK_PATH = os.path.join(SCRIPT_DIR, "cardback_resized.png")

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
DECK = [f"{rank}{suit}" for suit in SUITS for rank in RANKS]
QUEEN_CARD = "Q♥"

DEFAULT_QUBITS = 6
MAX_QUBITS = 14
SUCCESS_THRESHOLD = 0.9
HEATMAP_MIN_QUBITS = 11
PROB_RENDER_EPSILON = 1e-4

# Braun-inspired neutral palette
BG = "#f4f1ea"
PANEL = "#ece6dc"
PANEL_DARK = "#e1dbd1"
INK = "#1f1f1f"
MUTED = "#6f6b63"
ACCENT = "#bf3c30"
ACCENT_SOFT = "#d4a792"
CLASSICAL = "#2f7d52"


# ------------------------
# Grover helpers
# ------------------------
def custom_oracle(n, target_bin):
    qc = QuantumCircuit(n)
    for i, bit in enumerate(reversed(target_bin)):
        if bit == "0":
            qc.x(i)
    qc.h(n - 1)
    qc.mcx(list(range(n - 1)), n - 1)
    qc.h(n - 1)
    for i, bit in enumerate(reversed(target_bin)):
        if bit == "0":
            qc.x(i)
    return qc


def diffuser(n):
    qc = QuantumCircuit(n)
    qc.h(range(n))
    qc.x(range(n))
    qc.h(n - 1)
    qc.mcx(list(range(n - 1)), n - 1)
    qc.h(n - 1)
    qc.x(range(n))
    qc.h(range(n))
    return qc


# ------------------------
# Card widgets
# ------------------------
class CardLabel(QLabel):
    """Visual playing card used for the 6-qubit (52-card) mode."""

    def __init__(self, index, name):
        super().__init__()
        self.index = index
        self.name = name
        self.highlight_classical = False
        self.setFixedSize(65, 95)
        self.revealed = False
        self.probability = 0.0
        self.show_name = False

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: {BG}; border: 1px solid #c5bfb4; border-radius: 2px;"
        )

        face_path = os.path.join(SCRIPT_DIR, "queen_face.png")
        self.queen_face = (
            QPixmap(face_path).scaled(
                60,
                90,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if os.path.exists(face_path)
            else QPixmap()
        )

        pixmap = QPixmap(CARD_BACK_PATH)
        self.back_image = (
            pixmap.scaled(
                60,
                90,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if not pixmap.isNull()
            else None
        )

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        if self.revealed:
            if not self.queen_face.isNull():
                painter.drawPixmap(2, 2, self.queen_face)
            else:
                painter.setPen(QColor(INK))
                painter.setFont(QFont("Helvetica", 20, QFont.Weight.DemiBold))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Q♥")
            return

        if self.show_name:
            painter.setPen(QColor(INK))
            painter.setFont(QFont("Helvetica", 15, QFont.Weight.Medium))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.name)
        elif self.back_image and not self.back_image.isNull():
            painter.drawPixmap(2, 2, self.back_image)

        alpha = max(min(int(self.probability * 255 * 3.5), 225), 18) if self.probability > 0 else 14
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(191, 60, 48, alpha))
        cx = self.width() // 2
        cy = self.height() - 10
        painter.drawEllipse(cx - 3, cy - 3, 6, 6)

        if self.highlight_classical:
            pen = QPen(QColor(CLASSICAL), 2)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))


class CellLabel(QLabel):
    """Compact square for n>6 qubits (virtual cards / states)."""

    def __init__(self, index, size_px=24):
        super().__init__()
        self.index = index
        self.highlight_classical = False
        self.revealed = False
        self.probability = 0.0
        self.show_name = False
        self.size_px = size_px
        self._apply_size()

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: {BG}; border: 1px solid #cdc6bb; font-size: 9px; color: {INK};"
        )

    def _apply_size(self):
        self.setFixedSize(self.size_px, self.size_px)

    def set_cell_size(self, new_size):
        self.size_px = max(10, int(new_size))
        self._apply_size()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        alpha = max(min(int(self.probability * 255 * 3.5), 200), 16) if self.probability > 0 else 0
        if alpha > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(191, 60, 48, alpha))
            painter.drawRect(self.rect())

        if self.show_name:
            painter.setPen(QColor(INK))
            fs = max(7, min(11, int(self.size_px * 0.38)))
            painter.setFont(QFont("Helvetica", fs))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.index))

        if self.highlight_classical:
            pen = QPen(QColor(CLASSICAL), 2)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))


# ------------------------
# Heatmap canvas for n >= 11
# ------------------------
class HeatmapCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.cols = 1
        self.rows = 1
        self.spacing = 1
        self.probs = {}
        self.classical_idx = None
        self.target_idx = None
        self.quantum_success = False

    def set_geometry(self, cols, rows, spacing=1):
        self.cols = max(1, cols)
        self.rows = max(1, rows)
        self.spacing = max(0, spacing)
        self.update()

    def set_data(self, probs, classical_idx, target_idx, quantum_success=False):
        self.probs = probs or {}
        self.classical_idx = classical_idx
        self.target_idx = target_idx
        self.quantum_success = quantum_success
        self.update()

    def _cell_rect(self, viewport_rect: QRect, r, c):
        width = viewport_rect.width()
        height = viewport_rect.height()
        cw = (width - (self.cols - 1) * self.spacing) / self.cols
        ch = (height - (self.rows - 1) * self.spacing) / self.rows
        x = viewport_rect.left() + c * (cw + self.spacing)
        y = viewport_rect.top() + r * (ch + self.spacing)
        return QRect(int(x), int(y), int(cw), int(ch))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BG))

        if self.cols <= 0 or self.rows <= 0:
            return

        viewport = self.rect()
        total = self.cols * self.rows
        for idx in range(total):
            r = idx // self.cols
            c = idx % self.cols
            rect = self._cell_rect(viewport, r, c)
            p = self.probs.get(idx, 0.0)
            painter.fillRect(rect, QColor(PANEL_DARK))
            if p > 0:
                alpha = max(16, min(int(p * 255 * 3.5), 220))
                painter.fillRect(rect, QColor(191, 60, 48, alpha))

        if self.classical_idx is not None:
            r = self.classical_idx // self.cols
            c = self.classical_idx % self.cols
            rect = self._cell_rect(viewport, r, c)
            painter.setPen(QPen(QColor(CLASSICAL), 2))
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

        if self.target_idx is not None and self.quantum_success:
            r = self.target_idx // self.cols
            c = self.target_idx % self.cols
            rect = self._cell_rect(viewport, r, c)
            painter.setPen(QPen(QColor(ACCENT), 2))
            painter.drawRect(rect.adjusted(2, 2, -3, -3))


# ------------------------
# Main app
# ------------------------
class GroverGame(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Grover vs Classical — Queen of Hearts")
        self.setMinimumSize(1200, 800)

        self.num_qubits = DEFAULT_QUBITS
        self.n_items = None
        self.deck = []
        self.queen_index = None
        self.queen_bin = None
        self.oracle = None
        self.diff = None

        self.classical_attempts = 0
        self.classical_counter = 0
        self.classical_done = False
        self.grover_iterations = 0
        self.grover_done = False
        self.reveal_mode = False
        self.quantum_steps = None

        self.quantum_batch = 1

        self.auto_classical = False
        self.auto_batch = 1
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._auto_step_classical)

        self._cols = 0
        self._rows = 0
        self._grid_spacing = 2

        self._build_ui()
        self._apply_theme()
        self._init_problem(self.num_qubits)
        QTimer.singleShot(0, self._relayout_if_needed)

    def _apply_theme(self):
        self.setStyleSheet(
            f"""
            QWidget {{
                background: {BG};
                color: {INK};
                font-family: Helvetica, Arial, sans-serif;
                font-size: 12px;
            }}
            QFrame#LeftPanel {{
                background: {PANEL};
                border-right: 1px solid #c6bfb4;
            }}
            QFrame#StatCard {{
                background: {PANEL_DARK};
                border: 1px solid #c8c1b6;
                border-radius: 2px;
                padding: 8px;
            }}
            QPushButton {{
                background: transparent;
                border: 1px solid #b6b0a5;
                border-radius: 2px;
                padding: 8px 12px;
                min-height: 18px;
            }}
            QPushButton:hover {{ background: #e7e2d9; }}
            QPushButton:pressed {{ background: #dcd5ca; }}
            QPushButton:disabled {{ color: #9a9489; border-color: #c9c3b8; }}
            QComboBox {{
                background: {BG};
                border: 1px solid #b6b0a5;
                border-radius: 2px;
                padding: 5px 8px;
                min-width: 110px;
            }}
            QScrollArea {{ border: none; }}
            QSlider::groove:horizontal {{
                border: none;
                height: 2px;
                background: #bbb4a8;
            }}
            QSlider::handle:horizontal {{
                background: {INK};
                border: none;
                width: 12px;
                margin: -5px 0;
                border-radius: 0;
            }}
            """
        )

    # ---------- UI ----------
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left_panel = QVBoxLayout()
        left_panel.setAlignment(Qt.AlignmentFlag.AlignTop)
        left_panel.setContentsMargins(24, 28, 24, 24)
        left_panel.setSpacing(12)

        self.kicker = QLabel("GROVER / CLASSICAL")
        self.kicker.setStyleSheet(f"font-size: 10px; letter-spacing: 1px; color: {MUTED};")
        left_panel.addWidget(self.kicker)

        self.title = QLabel("Searching for a hidden target")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 24px; font-weight: 500;")
        left_panel.addWidget(self.title)

        left_panel.addWidget(
            self._status_block("IBM Quantum System Two", "Online", "HERON / 133 QUBITS / TUNABLE COUPLER")
        )
        left_panel.addWidget(self._status_block("Classical Computer", "Online", "Linear scan baseline"))

        sel_row = QHBoxLayout()
        self.qubit_combo = QComboBox()
        for q in range(6, MAX_QUBITS + 1):
            self.qubit_combo.addItem(f"{q} qubits", q)
        self.qubit_combo.setCurrentIndex(0)
        self.apply_qubits_btn = QPushButton("Apply")
        self.apply_qubits_btn.clicked.connect(self._apply_qubits)
        sel_row.addWidget(QLabel("Qubits"))
        sel_row.addWidget(self.qubit_combo)
        sel_row.addWidget(self.apply_qubits_btn)
        left_panel.addLayout(sel_row)

        speed_row = QVBoxLayout()
        self.speed_label = QLabel("Classical speed: Brisk")
        self.speed_label.setStyleSheet(f"font-size: 11px; color: {MUTED};")
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(5)
        self.speed_slider.setValue(3)
        self.speed_slider.valueChanged.connect(self._update_speed_label)
        speed_row.addWidget(self.speed_label)
        speed_row.addWidget(self.speed_slider)
        left_panel.addLayout(speed_row)

        self.message = QLabel("Click → to begin")
        self.message.setWordWrap(True)
        self.message.setStyleSheet(
            f"font-size: 13px; line-height: 1.2; padding: 8px; background: {PANEL_DARK}; border: 1px solid #c8c1b6;"
        )
        left_panel.addWidget(self.message)

        button_row = QHBoxLayout()
        self.reveal_button = QPushButton("Reveal All")
        self.reveal_button.setCheckable(True)
        self.reveal_button.clicked.connect(self._toggle_reveal)
        button_row.addWidget(self.reveal_button)

        self.restart_button = QPushButton("Restart")
        self.restart_button.clicked.connect(self._restart_game)
        button_row.addWidget(self.restart_button)
        left_panel.addLayout(button_row)

        control = QHBoxLayout()
        self.attempts_label = QLabel("--")
        self.attempts_label.setFixedSize(80, 80)
        self.attempts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.attempts_label.setStyleSheet(
            f"background: {INK}; color: {BG}; font-size: 26px; font-weight: 500;"
        )

        self.next_button = QPushButton("→")
        self.next_button.setFixedSize(80, 80)
        self.next_button.setStyleSheet(
            f"background: {INK}; color: {BG}; font-size: 28px; border: none;"
        )
        self.next_button.clicked.connect(self._next_turn)

        control.addWidget(self.attempts_label)
        control.addWidget(self.next_button)
        left_panel.addLayout(control)

        left_frame = QFrame()
        left_frame.setObjectName("LeftPanel")
        left_frame.setLayout(left_panel)
        left_frame.setFixedWidth(340)
        root.addWidget(left_frame)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QFrame()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(self._grid_spacing)
        self.grid_host.setLayout(self.grid_layout)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll)

        self.heatmap = HeatmapCanvas()

    def _status_block(self, title, status, description=None):
        block = QVBoxLayout()
        block.setSpacing(2)

        name = QLabel(title)
        name.setStyleSheet("font-size: 13px; font-weight: 500;")
        block.addWidget(name)

        tone = ACCENT_SOFT if status == "Online" else "#b57f7f"
        online = QLabel(f"● {status}")
        online.setStyleSheet(f"font-size: 11px; color: {tone};")
        block.addWidget(online)

        if description:
            desc = QLabel(description)
            desc.setStyleSheet(f"font-size: 10px; color: {MUTED};")
            desc.setWordWrap(True)
            block.addWidget(desc)

        frame = QFrame()
        frame.setObjectName("StatCard")
        frame.setLayout(block)
        return frame

    # ---------- Problem set-up ----------
    def _apply_qubits(self):
        q = self.qubit_combo.currentData()
        if q != self.num_qubits:
            self._init_problem(q)
            QTimer.singleShot(0, self._relayout_if_needed)

    def _clear_grid_layout(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

    def _init_problem(self, num_qubits: int):
        self.auto_classical = False
        self.auto_timer.stop()
        self._clear_grid_layout()

        self.num_qubits = num_qubits
        self.n_items = 52 if num_qubits == 6 else (1 << num_qubits)
        self.classical_attempts = 0
        self.classical_counter = 0
        self.classical_done = False
        self.grover_iterations = 0
        self.grover_done = False
        self.quantum_steps = None
        self.reveal_mode = False
        self.reveal_button.setChecked(False)
        self.reveal_button.setText("Reveal All")
        self.attempts_label.setText("--")
        self.next_button.setDisabled(False)
        self.message.setText("Click → to begin")

        if self.num_qubits == 6:
            self.deck = DECK[:]
            random.shuffle(self.deck)
            self.queen_index = self.deck.index(QUEEN_CARD)
            self.queen_bin = format(self.queen_index, f"0{self.num_qubits}b")
            self.title.setText("Searching Queen of Hearts (52 cards)")
        else:
            self.deck = None
            self.queen_index = random.randrange(self.n_items)
            self.queen_bin = format(self.queen_index, f"0{self.num_qubits}b")
            self.title.setText(f"Searching target state among {self.n_items} states")

        self.oracle = custom_oracle(self.num_qubits, self.queen_bin)
        self.diff = diffuser(self.num_qubits)
        self.quantum_batch = 5 if self.num_qubits >= HEATMAP_MIN_QUBITS + 1 else 1

        self.cards = []
        if self.num_qubits < HEATMAP_MIN_QUBITS:
            self.scroll.takeWidget()
            self.scroll.setWidget(self.grid_host)
            cols = int(math.sqrt(self.n_items))
            rows = math.ceil(self.n_items / cols)
            self._cols, self._rows = cols, rows
            r = c = 0
            for idx in range(self.n_items):
                if self.num_qubits == 6:
                    row = idx // 13
                    col = idx % 13
                    name = self.deck[idx]
                    card = CardLabel(idx, name)
                    self.cards.append(card)
                    self.grid_layout.addWidget(card, row, col)
                else:
                    cell = CellLabel(idx, size_px=24)
                    self.cards.append(cell)
                    self.grid_layout.addWidget(cell, r, c)
                    c += 1
                    if c >= cols:
                        c = 0
                        r += 1
        else:
            self.scroll.takeWidget()
            self.scroll.setWidget(self.heatmap)
            cols = int(math.sqrt(self.n_items))
            rows = math.ceil(self.n_items / cols)
            self._cols, self._rows = cols, rows
            self.heatmap.set_geometry(cols, rows, spacing=1)
            self.cards = []

    # ---------- Dynamic layout ----------
    def _relayout_if_needed(self):
        if self.num_qubits < HEATMAP_MIN_QUBITS:
            vp = self.scroll.viewport()
            vp_w = max(100, vp.width())
            vp_h = max(100, vp.height())
            spacing = self._grid_spacing
            cols, rows = self._cols, self._rows
            cell_w = (vp_w - (cols - 1) * spacing - 2) // cols
            cell_h = (vp_h - (rows - 1) * spacing - 2) // rows
            cell = max(10, min(cell_w, cell_h))
            for w in self.cards:
                if isinstance(w, CellLabel):
                    w.set_cell_size(cell)
            if self.num_qubits >= HEATMAP_MIN_QUBITS - 1 and cell < 20 and self._grid_spacing != 1:
                self._grid_spacing = 1
                self.grid_layout.setSpacing(self._grid_spacing)
                self._relayout_if_needed()
        else:
            self.heatmap.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._relayout_if_needed)

    # ---------- Interaction ----------
    def _toggle_reveal(self):
        self.reveal_mode = not self.reveal_mode
        if self.num_qubits < HEATMAP_MIN_QUBITS:
            for card in self.cards:
                card.show_name = self.reveal_mode
                card.update()
        self.reveal_button.setText("Hide All" if self.reveal_mode else "Reveal All")

    def _restart_game(self):
        self._init_problem(self.num_qubits)
        QTimer.singleShot(0, self._relayout_if_needed)

    def _classical_guess(self):
        if self.classical_done or self.classical_counter >= self.n_items:
            return None
        idx = self.classical_counter
        self.classical_counter += 1
        return idx

    def _apply_probs_to_view(self, probs, classical_index):
        if self.num_qubits < HEATMAP_MIN_QUBITS:
            for card in self.cards:
                card.probability = probs.get(card.index, 0.0) if probs else 0.0
                card.highlight_classical = card.index == classical_index
                card.revealed = (
                    self.num_qubits == 6
                    and card.index == self.queen_index
                    and self.grover_done
                )
                card.update()
        else:
            self.heatmap.set_data(
                probs,
                classical_index,
                self.queen_index,
                quantum_success=self.grover_done,
            )

    # ---------- Auto classical params ----------
    def _update_speed_label(self):
        labels = {
            1: "Classical speed: Languid",
            2: "Classical speed: Steady",
            3: "Classical speed: Brisk",
            4: "Classical speed: Fast",
            5: "Classical speed: Unseemly",
        }
        self.speed_label.setText(labels.get(self.speed_slider.value(), "Classical speed"))

    def _configure_auto_speed(self):
        v = self.speed_slider.value()
        if v == 1:
            interval, batch = 60, 1
        elif v == 2:
            interval, batch = 25, 2
        elif v == 3:
            interval, batch = 10, 8
        elif v == 4:
            interval, batch = 4, 16
        else:
            interval, batch = 1, 64

        if self.num_qubits >= 13:
            batch = max(batch, 32)
            interval = min(interval, 3)
        self.auto_batch = batch
        self.auto_timer.setInterval(interval)

    def _auto_step_classical(self):
        if not self.auto_classical:
            self.auto_timer.stop()
            return

        for _ in range(self.auto_batch):
            classical_index = self._classical_guess()
            if classical_index is None:
                self.auto_classical = False
                self.auto_timer.stop()
                self.next_button.setDisabled(False)
                break

            self.classical_attempts += 1
            self._update_attempts_label()
            classical_found = classical_index == self.queen_index
            self._apply_probs_to_view({}, classical_index)

            if classical_found:
                self.classical_done = True
                self.auto_classical = False
                self.auto_timer.stop()
                if self.quantum_steps is not None:
                    self.message.setText(
                        f"Quantum found in {self.quantum_steps} iterations. "
                        f"Classical needed {self.classical_attempts} checks to catch up."
                    )
                else:
                    self.message.setText("Classical algorithm found the target!")
                self.next_button.setDisabled(False)
                break

    def _run_grover_exact(self, iterations: int):
        n = self.num_qubits
        qc = QuantumCircuit(n)
        qc.h(range(n))
        for _ in range(iterations):
            qc.compose(self.oracle, inplace=True)
            qc.compose(self.diff, inplace=True)
        sv = Statevector.from_instruction(qc)
        probs = sv.probabilities()
        return {i: float(p) for i, p in enumerate(probs) if p > PROB_RENDER_EPSILON}

    def _update_attempts_label(self):
        display = max(self.classical_attempts, self.grover_iterations)
        self.attempts_label.setText(f"{display:02d}" if display else "--")

    def _next_turn(self):
        if self.auto_classical:
            return

        classical_index = self._classical_guess()
        if classical_index is not None:
            self.classical_attempts += 1
        classical_found_now = classical_index == self.queen_index
        if classical_found_now:
            self.classical_done = True

        final_probs = {}
        if not self.grover_done:
            for _ in range(self.quantum_batch):
                self.grover_iterations += 1
                final_probs = self._run_grover_exact(self.grover_iterations)
                if final_probs.get(self.queen_index, 0.0) > SUCCESS_THRESHOLD:
                    self.grover_done = True
                    self.quantum_steps = self.grover_iterations
                    break

        self._update_attempts_label()
        self._apply_probs_to_view(final_probs, classical_index)

        if self.grover_done and self.classical_done:
            self.message.setText(
                f"Both found the target. Quantum: {self.quantum_steps} iterations. "
                f"Classical: {self.classical_attempts} checks."
            )
        elif self.grover_done and not self.classical_done:
            self.message.setText(
                f"Quantum found in {self.quantum_steps} iterations. "
                "Classical is catching up…"
            )
            self.auto_classical = True
            self.next_button.setDisabled(True)
            self._configure_auto_speed()
            self.auto_timer.start()
        elif classical_found_now and not self.grover_done:
            if self.num_qubits == 6:
                self.message.setText(
                    f"Classical found the Queen in {self.classical_attempts} checks! "
                    "Grover still searching…"
                )
            else:
                self.message.setText(
                    f"Classical found the target in {self.classical_attempts} checks! "
                    "Grover still searching…"
                )
        else:
            if self.num_qubits == 6:
                classical_bit = "already found" if classical_index is None else f"checked {self.deck[classical_index]}"
            else:
                classical_bit = "already found" if classical_index is None else f"checked index {classical_index}"
            self.message.setText(
                f"Grover iter {self.grover_iterations}. Classical {classical_bit}."
            )


def main():
    app = QApplication(sys.argv)
    window = GroverGame()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
