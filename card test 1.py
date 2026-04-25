```python
import sys
import os
import math
import random
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFrame, QComboBox, QScrollArea, QSlider
)
from PyQt6.QtGui import QPixmap, QFont, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QTimer, QRect

from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# ------------------------
# Assets & deck
# ------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARD_BACK_PATH = os.path.join(SCRIPT_DIR, "cardback_resized.png")

suits = ['♠', '♥', '♦', '♣']
ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
deck = [f"{rank}{suit}" for suit in suits for rank in ranks]
queen_card = "Q♥"

DEFAULT_QUBITS = 6
MAX_QUBITS = 14
SUCCESS_THRESHOLD = 0.9   # Grover is "done" once target probability exceeds this
HEATMAP_MIN_QUBITS = 11   # Switch to heatmap view at/above this qubit count
PROB_RENDER_EPSILON = 1e-4  # Ignore negligible amplitudes when rendering

# ------------------------
# Grover helpers
# ------------------------
def custom_oracle(n, target_bin):
    qc = QuantumCircuit(n)
    for i, bit in enumerate(reversed(target_bin)):
        if bit == '0':
            qc.x(i)
    qc.h(n - 1)
    qc.mcx(list(range(n - 1)), n - 1)
    qc.h(n - 1)
    for i, bit in enumerate(reversed(target_bin)):
        if bit == '0':
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
        self.setStyleSheet("border: 2px solid grey; background: white;")

        face_path = os.path.join(SCRIPT_DIR, "queen_face.png")
        self.queen_face = QPixmap(face_path).scaled(
            60, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ) if os.path.exists(face_path) else QPixmap()

        pixmap = QPixmap(CARD_BACK_PATH)
        self.back_image = pixmap.scaled(
            60, 90, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        ) if not pixmap.isNull() else None

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        if self.revealed:
            if not self.queen_face.isNull():
                painter.drawPixmap(2, 2, self.queen_face)
            else:
                painter.setPen(Qt.GlobalColor.black)
                painter.setFont(QFont("Arial", 20))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Q♥")
            return

        if self.show_name:
            painter.setPen(Qt.GlobalColor.black)
            painter.setFont(QFont("Arial", 16))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.name)
        elif self.back_image and not self.back_image.isNull():
            painter.drawPixmap(2, 2, self.back_image)

        # Red probability glow (dot)
        alpha = max(min(int(self.probability * 255 * 3.5), 255), 20) if self.probability > 0 else 20
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 0, 0, alpha))
        cx = self.width() // 2
        cy = self.height() - 10
        painter.drawEllipse(cx - 4, cy - 4, 8, 8)

        # Classical guess outline
        if self.highlight_classical:
            pen = QPen(Qt.GlobalColor.green, 3)
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
        self.setStyleSheet("border: 1px solid #999; background: white; font-size: 9px;")

    def _apply_size(self):
        self.setFixedSize(self.size_px, self.size_px)

    def set_cell_size(self, new_size):
        self.size_px = max(10, int(new_size))  # clamp
        self._apply_size()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)

        # Probability glow fills the background subtly
        alpha = max(min(int(self.probability * 255 * 3.5), 255), 20) if self.probability > 0 else 0
        if alpha > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 0, 0, alpha))
            painter.drawRect(self.rect())

        # Index text (shown when reveal toggled)
        if self.show_name:
            painter.setPen(Qt.GlobalColor.black)
            fs = max(7, min(11, int(self.size_px * 0.38)))
            painter.setFont(QFont("Arial", fs))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.index))

        # Classical guess outline
        if self.highlight_classical:
            pen = QPen(Qt.GlobalColor.green, 2)
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
        self.probs = {}           # dict int->float
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

    def sizeHint(self):
        return super().sizeHint()

    def _cell_rect(self, viewport_rect: QRect, r, c):
        # compute cell rect given current widget size and grid
        W = viewport_rect.width()
        H = viewport_rect.height()
        cw = (W - (self.cols - 1) * self.spacing) / self.cols
        ch = (H - (self.rows - 1) * self.spacing) / self.rows
        x = viewport_rect.left() + c * (cw + self.spacing)
        y = viewport_rect.top() + r * (ch + self.spacing)
        return QRect(int(x), int(y), int(cw), int(ch))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)

        if self.cols <= 0 or self.rows <= 0:
            return

        # Draw heatmap
        viewport = self.rect()
        N = self.cols * self.rows
        for idx in range(N):
            r = idx // self.cols
            c = idx % self.cols
            rect = self._cell_rect(viewport, r, c)
            p = self.probs.get(idx, 0.0)
            if p > 0:
                alpha = max(20, min(int(p * 255 * 3.5), 255))
                painter.fillRect(rect, QColor(255, 0, 0, alpha))

        # Outline classical position
        if self.classical_idx is not None:
            r = self.classical_idx // self.cols
            c = self.classical_idx % self.cols
            rect = self._cell_rect(viewport, r, c)
            pen = QPen(Qt.GlobalColor.green, 2)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

        # Outline target after Grover success (red border)
        if self.target_idx is not None and self.quantum_success:
            r = self.target_idx // self.cols
            c = self.target_idx % self.cols
            rect = self._cell_rect(viewport, r, c)
            pen = QPen(Qt.GlobalColor.red, 2)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(2, 2, -3, -3))

# ------------------------
# Main app
# ------------------------
class GroverGame(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Grover vs Classical — The Queen of Hearts (Scalable)")
        self.setMinimumSize(1200, 800)

        self.num_qubits = DEFAULT_QUBITS
        self.n_items = None  # depends on qubits
        self.deck = []
        self.queen_index = None
        self.queen_bin = None
        self.oracle = None
        self.diff = None

        # Separate counters — no more conflation via self.turn
        self.classical_attempts = 0
        self.classical_counter = 0      # O(1) next-index cursor
        self.classical_done = False     # set once classical has matched the target
        self.grover_iterations = 0
        self.grover_done = False
        self.reveal_mode = False
        self.quantum_steps = None  # capture steps when Grover first succeeds

        # quantum batch for n>11
        self.quantum_batch = 1

        # auto classical advance (adaptive speed + batching)
        self.auto_classical = False
        self.auto_batch = 1
        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._auto_step_classical)

        # grid geometry
        self._cols = 0
        self._rows = 0
        self._grid_spacing = 2  # tighter spacing for dense grids

        self._build_ui()
        self._init_problem(self.num_qubits)  # creates grid, target, circuits
        QTimer.singleShot(0, self._relayout_if_needed)

    # ---------- UI ----------
    def _build_ui(self):
        root = QHBoxLayout(self)

        # Left panel
        left_panel = QVBoxLayout()
        left_panel.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.title = QLabel("Searching for a hidden target")
        self.title.setStyleSheet("font-size: 20px;")
        left_panel.addWidget(self.title)

        left_panel.addWidget(self._status_block("IBM Quantum System Two", "Online",
                            "HERON<br>133 QUBITS<br>TUNABLE-COUPLER"))
        left_panel.addWidget(self._status_block("Classical Computer", "Online"))

        # Qubit selector
        sel_row = QHBoxLayout()
        self.qubit_combo = QComboBox()
        for q in range(6, MAX_QUBITS + 1):
            self.qubit_combo.addItem(f"{q} qubits", q)
        self.qubit_combo.setCurrentIndex(0)  # 6
        self.apply_qubits_btn = QPushButton("Apply")
        self.apply_qubits_btn.clicked.connect(self._apply_qubits)
        sel_row.addWidget(QLabel("Qubits:"))
        sel_row.addWidget(self.qubit_combo)
        sel_row.addWidget(self.apply_qubits_btn)
        left_panel.addLayout(sel_row)

        # Speed slider for classical catch-up
        speed_row = QVBoxLayout()
        self.speed_label = QLabel("Classical speed: Brisk")
        self.speed_label.setStyleSheet("font-size: 12px; color: #333;")
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setMinimum(1)
        self.speed_slider.setMaximum(5)
        self.speed_slider.setValue(3)  # Default: Brisk
        self.speed_slider.valueChanged.connect(self._update_speed_label)
        speed_row.addWidget(self.speed_label)
        speed_row.addWidget(self.speed_slider)
        left_panel.addLayout(speed_row)

        # Message block
        self.message = QLabel("Click → to begin")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("font-size: 14px; padding: 10px;")
        left_panel.addWidget(self.message)

        # Buttons: Reveal & Restart
        button_row = QHBoxLayout()
        self.reveal_button = QPushButton("Reveal All")
        self.reveal_button.setCheckable(True)
        self.reveal_button.clicked.connect(self._toggle_reveal)
        button_row.addWidget(self.reveal_button)

        self.restart_button = QPushButton("Restart")
        self.restart_button.clicked.connect(self._restart_game)
        button_row.addWidget(self.restart_button)
        left_panel.addLayout(button_row)

        # Turn control
        control = QHBoxLayout()
        self.attempts_label = QLabel("--")
        self.attempts_label.setFixedSize(80, 80)
        self.attempts_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.attempts_label.setStyleSheet("background-color: #444; color: white; font-size: 28px;")

        self.next_button = QPushButton("→")
        self.next_button.setFixedSize(80, 80)
        self.next_button.setStyleSheet("background-color: #333; color: white; font-size: 24px;")
        self.next_button.clicked.connect(self._next_turn)

        control.addWidget(self.attempts_label)
        control.addWidget(self.next_button)
        left_panel.addLayout(control)

        left_frame = QFrame()
        left_frame.setLayout(left_panel)
        left_frame.setFixedWidth(320)
        left_frame.setStyleSheet("background-color: #ddd;")
        root.addWidget(left_frame)

        # Right: either grid of widgets (<=10) or a heatmap canvas (>=11)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QFrame()
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(self._grid_spacing)
        self.grid_host.setLayout(self.grid_layout)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll)

        # Heatmap canvas that we swap in when needed
        self.heatmap = HeatmapCanvas()

    def _status_block(self, title, status, description=None):
        block = QVBoxLayout()
        name = QLabel(f"<b>{title}</b>")
        name.setStyleSheet("font-size: 14px;")
        block.addWidget(name)

        online = QLabel("🟢 Online" if status == "Online" else "🔴 Offline")
        online.setStyleSheet("font-size: 12px; color: green;" if status == "Online" else "color: red;")
        block.addWidget(online)

        if description:
            desc = QLabel(description)
            desc.setStyleSheet("font-size: 10px; color: #555;")
            desc.setWordWrap(True)
            block.addWidget(desc)

        frame = QFrame()
        frame.setLayout(block)
        frame.setStyleSheet("background-color: #ccc; padding: 10px; margin-bottom: 10px;")
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
        # Stop any auto run
        self.auto_classical = False
        self.auto_timer.stop()

        # Clear previous view
        self._clear_grid_layout()

        # Decide which view to use
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

        # Target selection & circuits
        if self.num_qubits == 6:
            self.deck = deck[:]
            random.shuffle(self.deck)
            self.queen_index = self.deck.index(queen_card)
            self.queen_bin = format(self.queen_index, f"0{self.num_qubits}b")
            self.title.setText("Searching Queen of Hearts (52 cards)")
        else:
            self.deck = None
            self.queen_index = random.randrange(self.n_items)
            self.queen_bin = format(self.queen_index, f"0{self.num_qubits}b")
            self.title.setText(f"Searching target state among {self.n_items} states")

        self.oracle = custom_oracle(self.num_qubits, self.queen_bin)
        self.diff = diffuser(self.num_qubits)

        # Quantum batch setup
        self.quantum_batch = 5 if self.num_qubits >= HEATMAP_MIN_QUBITS + 1 else 1

        # Build view
        self.cards = []
        if self.num_qubits < HEATMAP_MIN_QUBITS:
            # Widget grid
            self.scroll.takeWidget()
            self.scroll.setWidget(self.grid_host)
            cols = int(math.sqrt(self.n_items))
            rows = math.ceil(self.n_items / cols)
            self._cols, self._rows = cols, rows
            r = c = 0
            for idx in range(self.n_items):
                if self.num_qubits == 6:
                    # 4x13 classic layout
                    row = idx // 13
                    col = idx % 13
                    name = self.deck[idx]
                    card = CardLabel(idx, name)
                    self.cards.append(card)
                    self.grid_layout.addWidget(card, row, col)
                else:
                    cell = CellLabel(idx, size_px=24)  # resized later
                    self.cards.append(cell)
                    self.grid_layout.addWidget(cell, r, c)
                    c += 1
                    if c >= cols:
                        c = 0
                        r += 1
        else:
            # Heatmap view
            self.scroll.takeWidget()
            self.scroll.setWidget(self.heatmap)
            cols = int(math.sqrt(self.n_items))
            rows = math.ceil(self.n_items / cols)
            self._cols, self._rows = cols, rows
            self.heatmap.set_geometry(cols, rows, spacing=1)
            self.cards = []  # not used in heatmap mode

    # ---------- Dynamic layout helpers ----------
    def _relayout_if_needed(self):
        """Autosize tiles for n<HEATMAP_MIN_QUBITS; heatmap fills viewport otherwise."""
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
        # Deterministic linear scan (simple baseline) — O(1) per call.
        # Stops advancing once classical has already matched the target.
        if self.classical_done or self.classical_counter >= self.n_items:
            return None
        idx = self.classical_counter
        self.classical_counter += 1
        return idx

    def _apply_probs_to_view(self, probs, classical_index):
        if self.num_qubits < HEATMAP_MIN_QUBITS:
            # Update widgets
            for card in self.cards:
                card.probability = probs.get(card.index, 0.0) if probs else 0.0
                card.highlight_classical = (card.index == classical_index)
                card.revealed = (self.num_qubits == 6 and card.index == self.queen_index and self.grover_done)
                card.update()
        else:
            # Heatmap render; mark target after success
            self.heatmap.set_data(probs, classical_index, self.queen_index, quantum_success=self.grover_done)

    # ---------- Auto classical params ----------
    def _update_speed_label(self):
        labels = {
            1: "Classical speed: Languid",
            2: "Classical speed: Steady",
            3: "Classical speed: Brisk",
            4: "Classical speed: Fast",
            5: "Classical speed: Unseemly"
        }
        self.speed_label.setText(labels.get(self.speed_slider.value(), "Classical speed"))

    def _configure_auto_speed(self):
        """Set interval + batch size for classical catch-up from the slider."""
        v = self.speed_slider.value()
        if v == 1:
            interval, batch = 60, 1
        elif v == 2:
            interval, batch = 25, 2
        elif v == 3:
            interval, batch = 10, 8
        elif v == 4:
            interval, batch = 4, 16
        else:  # 5
            interval, batch = 1, 64
        # For very large n, bump batch a bit
        if self.num_qubits >= 13:
            batch = max(batch, 32)
            interval = min(interval, 3)
        self.auto_batch = batch
        self.auto_timer.setInterval(interval)

    def _auto_step_classical(self):
        """Advance classical guesses automatically until it finds the target."""
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

            classical_found = (classical_index == self.queen_index)
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
        """Return exact probability dict from statevector simulation.

        Faster and noise-free compared to shot-based sampling: a k-iteration
        Grover circuit has a well-defined amplitude at every basis state, and
        we can read that off directly rather than estimating it from 1000 shots.
        """
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
            return  # ignore clicks while auto-running

        # Classical advances once per click (manual mode), unless already done.
        classical_index = self._classical_guess()
        if classical_index is not None:
            self.classical_attempts += 1
        classical_found_now = (classical_index == self.queen_index)
        if classical_found_now:
            self.classical_done = True

        # Quantum: skip entirely if Grover already succeeded (major fix — no
        # wasted ~100-iteration re-simulations after completion).
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

        # Status text and auto-run trigger
        if self.grover_done and self.classical_done:
            self.message.setText(
                f"Both found the target. "
                f"Quantum: {self.quantum_steps} iterations. "
                f"Classical: {self.classical_attempts} checks."
            )
        elif self.grover_done and not self.classical_done:
            # Quantum won — run classical forward until it finds the target too.
            self.message.setText(
                f"Quantum found in {self.quantum_steps} iterations. "
                f"Classical is catching up…"
            )
            self.auto_classical = True
            self.next_button.setDisabled(True)
            self._configure_auto_speed()
            self.auto_timer.start()
        elif classical_found_now and not self.grover_done:
            if self.num_qubits == 6:
                self.message.setText(
                    f"Classical found the Queen in {self.classical_attempts} checks! "
                    f"Grover still searching…"
                )
            else:
                self.message.setText(
                    f"Classical found the target in {self.classical_attempts} checks! "
                    f"Grover still searching…"
                )
        else:
            if self.num_qubits == 6:
                if classical_index is None:
                    classical_bit = "already found"
                else:
                    classical_bit = f"checked {self.deck[classical_index]}"
                self.message.setText(
                    f"Grover iter {self.grover_iterations}. Classical {classical_bit}."
                )
            else:
                if classical_index is None:
                    classical_bit = "already found"
                else:
                    classical_bit = f"checked index {classical_index}"
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
```

That's the complete file. When you've tested it and want to move on to the redesign, let me know which direction you want to go.