"""Main window (Arabic, right-to-left)."""

from __future__ import annotations

import copy
import logging
import os
import sys

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSlider, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import __version__
from ..capture import CaptureError
from ..config import GameProfile, data_dir
from ..controller import Controller
from ..pipeline import SubtitleEvent
from .overlay import OverlayWindow
from .region_picker import RegionPicker, bgr_to_qimage

log = logging.getLogger(__name__)

LEVEL_COLORS = {"ok": "#2e7d32", "info": "#455a64", "warn": "#ef6c00", "error": "#c62828"}
ORIGIN_NAMES = {"user": "تصحيحك", "cache": "من الذاكرة", "mixed": "مختلط", "none": "بدون ترجمة", "": "بدون ترجمة"}


class CorrectionDialog(QDialog):
    def __init__(self, english: str, arabic: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تصحيح الترجمة")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        src = QLabel(english)
        src.setLayoutDirection(Qt.LeftToRight)
        src.setWordWrap(True)
        src.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(QLabel("النص الإنجليزي:"))
        layout.addWidget(src)
        layout.addWidget(QLabel("الترجمة الصحيحة (تُستخدم دائمًا لهذه الجملة في هذه اللعبة):"))
        self.edit = QPlainTextEdit(arabic)
        self.edit.setFixedHeight(90)
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("حفظ")
        buttons.button(QDialogButtonBox.Cancel).setText("إلغاء")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText().strip()


class MainWindow(QMainWindow):
    deepl_result = Signal(bool, str)

    def __init__(self, controller: Controller):
        super().__init__()
        self.c = controller
        self.cfg = controller.cfg
        self.setWindowTitle(f"PlayTranslate {__version__}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(820, 680)
        self.overlay = OverlayWindow(self.cfg.style)
        self._last_event: SubtitleEvent | None = None
        self._loading = False
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self._flush_apply)
        self._pending = {"engines": False, "glossary": False}

        tabs = QTabWidget()
        tabs.addTab(self._build_run_tab(), "التشغيل")
        tabs.addTab(self._build_region_tab(), "منطقة الحوار")
        tabs.addTab(self._build_translate_tab(), "الترجمة")
        tabs.addTab(self._build_style_tab(), "الشكل")
        tabs.addTab(self._build_advanced_tab(), "متقدم")
        tabs.addTab(self._build_help_tab(), "مساعدة")
        self.setCentralWidget(tabs)

        c = self.c
        c.status.connect(self._on_status)
        c.subtitle.connect(self._on_subtitle)
        c.hidden.connect(self._on_hidden)
        c.geometry.connect(self._on_geometry)
        c.clients_changed.connect(self._on_clients)
        c.running_changed.connect(self._on_running)
        c.engines_message.connect(self._on_engines_message)
        c.overlay_sink.shown.connect(self.overlay.show_lines)
        c.overlay_sink.hidden.connect(self.overlay.clear)
        self.deepl_result.connect(self._on_deepl_result)

        self._load_profile_into_ui()
        self._refresh_addresses()
        c.start_server()
        self._on_clients(c.server.clients)
        if c.engine_problem:
            self._on_status(c.engine_problem, "warn")
        else:
            self._on_status("جاهز. شغّل PS Remote Play ثم اضغط «ابدأ».", "info")

    # ================================================================ tabs

    def _build_run_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        top = QHBoxLayout()
        self.start_btn = QPushButton("ابدأ")
        self.start_btn.setMinimumHeight(48)
        self.start_btn.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.start_btn.clicked.connect(self._toggle)
        top.addWidget(self.start_btn, 2)
        prof_box = QVBoxLayout()
        prof_box.addWidget(QLabel("اللعبة:"))
        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.currentTextChanged.connect(self._switch_profile)
        row.addWidget(self.profile_combo, 1)
        for text, slot in (("جديدة", self._new_profile), ("تسمية", self._rename_profile), ("حذف", self._delete_profile)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        prof_box.addLayout(row)
        top.addLayout(prof_box, 3)
        v.addLayout(top)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("padding: 6px; border-radius: 4px; background: #eceff1;")
        v.addWidget(self.status_label)

        where = QGroupBox("أين تظهر الترجمة")
        g = QGridLayout(where)
        self.tv_check = QCheckBox("على التلفزيون (تطبيق PlayTranslate في التلفزيون)")
        self.local_check = QCheckBox("فوق نافذة Remote Play على اللابتوب (لو اللابتوب موصول بالتلفزيون)")
        self.tv_check.toggled.connect(lambda on: self._set("send_to_tv", on))
        self.local_check.toggled.connect(self._toggle_local)
        self.tv_label = QLabel()
        self.addr_label = QLabel()
        self.addr_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.addr_label.setOpenExternalLinks(True)
        test_btn = QPushButton("إرسال نص تجربة")
        test_btn.clicked.connect(lambda: (self.c.send_test(), QTimer.singleShot(4000, self.c.hide_test)))
        g.addWidget(self.tv_check, 0, 0, 1, 2)
        g.addWidget(self.local_check, 1, 0, 1, 2)
        g.addWidget(self.tv_label, 2, 0)
        g.addWidget(test_btn, 2, 1)
        g.addWidget(self.addr_label, 3, 0, 1, 2)
        v.addWidget(where)

        last = QGroupBox("آخر جملة")
        lv = QVBoxLayout(last)
        self.en_label = QLabel("—")
        self.en_label.setLayoutDirection(Qt.LeftToRight)
        self.en_label.setAlignment(Qt.AlignLeft)
        self.en_label.setWordWrap(True)
        self.ar_label = QLabel("—")
        self.ar_label.setWordWrap(True)
        self.ar_label.setStyleSheet("font-size: 18px;")
        self.timing_label = QLabel("")
        self.timing_label.setStyleSheet("color: #607d8b;")
        fix_btn = QPushButton("تصحيح هذه الترجمة")
        fix_btn.clicked.connect(lambda: self._correct(self._last_event))
        lv.addWidget(self.en_label)
        lv.addWidget(self.ar_label)
        row = QHBoxLayout()
        row.addWidget(self.timing_label, 1)
        row.addWidget(fix_btn)
        lv.addLayout(row)
        v.addWidget(last)

        v.addWidget(QLabel("السجل (انقر مرتين على أي جملة لتصحيحها):"))
        self.history = QListWidget()
        self.history.itemDoubleClicked.connect(lambda item: self._correct(item.data(Qt.UserRole)))
        v.addWidget(self.history, 1)
        return w

    def _build_region_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        info = QLabel("حدّد مكان الترجمة الإنجليزية في اللعبة مرة وحدة لكل لعبة. شغّل اللعبة وانتظر "
                      "لين تطلع جملة على الشاشة، ثم اضغط الزر.")
        info.setWordWrap(True)
        v.addWidget(info)
        pick = QPushButton("حدّد منطقة الحوار من الشاشة")
        pick.setMinimumHeight(40)
        pick.clicked.connect(self._pick_region)
        v.addWidget(pick)
        self.region_label = QLabel()
        v.addWidget(self.region_label)

        form = QFormLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("فاتح (أبيض أو أصفر) — أغلب الألعاب", "light")
        self.mode_combo.addItem("داكن على خلفية فاتحة", "dark")
        self.mode_combo.addItem("تلقائي", "auto")
        self.mode_combo.currentIndexChanged.connect(lambda: self._set_profile("text_mode", self.mode_combo.currentData()))
        form.addRow("لون الترجمة في اللعبة:", self.mode_combo)
        self.sens_slider = QSlider(Qt.Horizontal)
        self.sens_slider.setRange(25, 140)
        self.sens_slider.valueChanged.connect(lambda v: self._set_profile("sensitivity", v))
        form.addRow("حساسية الكشف (يسار = يلتقط النص الباهت، يمين = يتجاهل المشهد):", self.sens_slider)
        self.speaker_check = QCheckBox("افصل اسم المتكلم (مثل ARTHUR:) واعرضه بلون مختلف")
        self.speaker_check.toggled.connect(lambda on: self._set_profile("split_speaker", on))
        form.addRow(self.speaker_check)
        v.addLayout(form)

        v.addWidget(QLabel("آخر ما قرأته الأداة (للتأكد إن المنطقة صحيحة):"))
        self.crop_preview = QLabel()
        self.crop_preview.setMinimumHeight(90)
        self.crop_preview.setAlignment(Qt.AlignCenter)
        self.crop_preview.setStyleSheet("background: #263238;")
        v.addWidget(self.crop_preview)
        v.addStretch(1)
        return w

    def _build_translate_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("DeepL (الأفضل، مجاني لحد 500 ألف حرف شهريًا)", "deepl")
        self.engine_combo.addItem("Argos (بدون إنترنت، جودة أقل)", "argos")
        self.engine_combo.addItem("بدون ترجمة (عرض الإنجليزي، للتجربة)", "none")
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(self.cfg.translator)))
        self.engine_combo.currentIndexChanged.connect(
            lambda: self._set("translator", self.engine_combo.currentData(), engines=True))
        form.addRow("محرك الترجمة:", self.engine_combo)

        key_row = QHBoxLayout()
        self.key_edit = QLineEdit(self.cfg.deepl_api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        self.key_edit.setPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx")
        self.key_edit.editingFinished.connect(
            lambda: self._set("deepl_api_key", self.key_edit.text().strip(), engines=True))
        show = QCheckBox("إظهار")
        show.toggled.connect(lambda on: self.key_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        test = QPushButton("اختبار المفتاح والرصيد")
        test.clicked.connect(self._test_key)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(show)
        key_row.addWidget(test)
        form.addRow("مفتاح DeepL:", key_row)
        self.key_result = QLabel()
        self.key_result.setWordWrap(True)
        form.addRow("", self.key_result)
        link = QLabel('<a href="https://www.deepl.com/pro-api">احصل على مفتاح DeepL مجاني من هنا</a>')
        link.setOpenExternalLinks(True)
        form.addRow("", link)
        self.context_check = QCheckBox("أرسل الجملتين السابقتين كسياق (ترجمة أدق، بدون تكلفة إضافية)")
        self.context_check.setChecked(self.cfg.use_context)
        self.context_check.toggled.connect(lambda on: self._set("use_context", on))
        form.addRow(self.context_check)
        v.addLayout(form)

        box = QGroupBox("قاموس مصطلحات هذه اللعبة (أسماء وكلمات تترجم دائمًا بنفس الشكل)")
        bv = QVBoxLayout(box)
        self.glossary_table = QTableWidget(0, 2)
        self.glossary_table.setHorizontalHeaderLabels(["بالإنجليزي", "بالعربي"])
        self.glossary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.glossary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.glossary_table.itemChanged.connect(self._glossary_changed)
        bv.addWidget(self.glossary_table)
        row = QHBoxLayout()
        add = QPushButton("إضافة")
        add.clicked.connect(self._glossary_add)
        rem = QPushButton("حذف المحدد")
        rem.clicked.connect(self._glossary_remove)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        bv.addLayout(row)
        v.addWidget(box, 1)
        return w

    def _build_style_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        s = self.cfg.style
        self.size_spin = QSpinBox()
        self.size_spin.setRange(16, 120)
        self.size_spin.setValue(s.font_size)
        self.size_spin.valueChanged.connect(lambda v: self._set_style("font_size", v))
        form.addRow("حجم الخط (على شاشة 1080p):", self.size_spin)
        self.font_edit = QLineEdit(s.font_family)
        self.font_edit.editingFinished.connect(lambda: self._set_style("font_family", self.font_edit.text().strip() or "Noto Naskh Arabic"))
        form.addRow("نوع الخط:", self.font_edit)
        for label, attr in (("لون النص:", "text_color"), ("لون اسم المتكلم:", "speaker_color"), ("لون الخلفية:", "background_color")):
            btn = QPushButton()
            self._paint_color_button(btn, getattr(s, attr))
            btn.clicked.connect(lambda _=False, a=attr, b=btn: self._pick_color(a, b))
            form.addRow(label, btn)
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0, 1)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(s.background_opacity)
        self.opacity_spin.valueChanged.connect(lambda v: self._set_style("background_opacity", round(v, 2)))
        form.addRow("شفافية الخلفية (0 = بدون خلفية):", self.opacity_spin)
        self.margin_spin = QDoubleSpinBox()
        self.margin_spin.setRange(0, 0.9)
        self.margin_spin.setSingleStep(0.01)
        self.margin_spin.setValue(s.bottom_margin)
        self.margin_spin.valueChanged.connect(lambda v: self._set_style("bottom_margin", round(v, 3)))
        form.addRow("المسافة من أسفل الشاشة (نسبة):", self.margin_spin)
        self.outline_check = QCheckBox("حد أسود حول الحروف")
        self.outline_check.setChecked(s.outline)
        self.outline_check.toggled.connect(lambda on: self._set_style("outline", on))
        form.addRow(self.outline_check)
        test = QPushButton("إرسال نص تجربة لمدة 6 ثوانٍ")
        test.clicked.connect(lambda: (self.c.send_test(), QTimer.singleShot(6000, self.c.hide_test)))
        form.addRow(test)
        return w

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.title_edit = QLineEdit(self.cfg.window_title)
        self.title_edit.setLayoutDirection(Qt.LeftToRight)
        self.title_edit.editingFinished.connect(lambda: self._set("window_title", self.title_edit.text().strip() or "PS Remote Play"))
        form.addRow("اسم نافذة اللعبة:", self.title_edit)
        self.ocr_combo = QComboBox()
        self.ocr_combo.addItem("تلقائي (Windows OCR ثم RapidOCR)", "auto")
        self.ocr_combo.addItem("Windows OCR فقط", "windows")
        self.ocr_combo.addItem("RapidOCR فقط (يعمل بدون لغة إنجليزية في ويندوز)", "rapid")
        self.ocr_combo.setCurrentIndex(max(0, self.ocr_combo.findData(self.cfg.ocr_engine)))
        self.ocr_combo.currentIndexChanged.connect(lambda: self._set("ocr_engine", self.ocr_combo.currentData()))
        form.addRow("محرك القراءة:", self.ocr_combo)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(2, 30)
        self.fps_spin.setValue(self.cfg.capture_fps)
        self.fps_spin.valueChanged.connect(lambda v: self._set("capture_fps", v))
        form.addRow("صور في الثانية:", self.fps_spin)
        self.linger_spin = QSpinBox()
        self.linger_spin.setRange(0, 5000)
        self.linger_spin.setSingleStep(100)
        self.linger_spin.setSuffix(" ms")
        self.linger_spin.setValue(self.cfg.linger_ms)
        self.linger_spin.valueChanged.connect(lambda v: self._set("linger_ms", v))
        form.addRow("إبقاء العربي بعد اختفاء الإنجليزي:", self.linger_spin)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.cfg.server_port)
        self.port_spin.valueChanged.connect(lambda v: self._set("server_port", v))
        form.addRow("منفذ الاتصال بالتلفزيون (يتطلب إعادة تشغيل):", self.port_spin)
        open_btn = QPushButton("فتح مجلد البيانات والسجلات")
        open_btn.clicked.connect(self._open_data_dir)
        form.addRow(open_btn)
        stats = QPushButton("عدد الجمل المحفوظة لهذه اللعبة")
        stats.clicked.connect(self._show_stats)
        form.addRow(stats)
        return w

    def _build_help_tab(self) -> QWidget:
        b = QTextBrowser()
        b.setOpenExternalLinks(True)
        b.setHtml(HELP_HTML)
        return b

    # ============================================================= helpers

    def _set(self, name, value, engines=False):
        if self._loading or getattr(self.cfg, name) == value:
            return
        setattr(self.cfg, name, value)
        self._schedule_apply(engines=engines)

    def _set_profile(self, name, value, glossary=False):
        if self._loading:
            return
        p = self.cfg.profile
        if getattr(p, name) == value:
            return
        setattr(p, name, value)
        self._schedule_apply(glossary=glossary)

    def _set_style(self, name, value):
        if self._loading:
            return
        setattr(self.cfg.style, name, value)
        self.cfg.style.normalize()
        self.overlay.set_style(self.cfg.style)
        self._schedule_apply()

    def _schedule_apply(self, engines=False, glossary=False):
        self._pending["engines"] |= engines
        self._pending["glossary"] |= glossary
        self._save_timer.start()

    def _flush_apply(self):
        engines, glossary = self._pending["engines"], self._pending["glossary"]
        self._pending = {"engines": False, "glossary": False}
        self.c.apply(engines_changed=engines, glossary_changed=glossary)
        self._refresh_addresses()

    def _paint_color_button(self, btn: QPushButton, color: str):
        btn.setText(color)
        btn.setStyleSheet(f"background: {color[:7]}; color: {'#000' if QColor(color).lightness() > 128 else '#fff'};")

    def _pick_color(self, attr: str, btn: QPushButton):
        color = QColorDialog.getColor(QColor(getattr(self.cfg.style, attr)), self, "اختر اللون")
        if color.isValid():
            value = color.name()
            self._paint_color_button(btn, value)
            self._set_style(attr, value)

    def _refresh_addresses(self):
        addrs = self.c.addresses()
        if not self.cfg.send_to_tv:
            self.addr_label.setText("الإرسال للتلفزيون متوقف.")
            return
        first = addrs[0] if addrs else f"127.0.0.1:{self.cfg.server_port}"
        self.addr_label.setText(
            f"عنوان هذا اللابتوب: <b dir='ltr'>{' أو '.join(addrs)}</b><br>"
            f"تجربة من أي جوال أو متصفح على نفس الشبكة: "
            f"<a href='http://{first}/overlay'>http://{first}/overlay</a>")

    # ============================================================= profiles

    def _load_profile_into_ui(self):
        self._loading = True
        try:
            self.profile_combo.blockSignals(True)
            self.profile_combo.clear()
            self.profile_combo.addItems(sorted(self.cfg.profiles))
            self.profile_combo.setCurrentText(self.cfg.active_profile)
            self.profile_combo.blockSignals(False)
            p = self.cfg.profile
            self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(p.text_mode)))
            self.sens_slider.setValue(p.sensitivity)
            self.speaker_check.setChecked(p.split_speaker)
            self.tv_check.setChecked(self.cfg.send_to_tv)
            self.local_check.setChecked(self.cfg.local_overlay)
            r = p.region
            self.region_label.setText(
                f"المنطقة الحالية: من {r.x:.0%} يمين/يسار، {r.y:.0%} من الأعلى، بعرض {r.w:.0%} وارتفاع {r.h:.0%}")
            self.glossary_table.blockSignals(True)
            self.glossary_table.setRowCount(0)
            for en, ar in sorted(p.glossary.items()):
                self._glossary_append(en, ar)
            self.glossary_table.blockSignals(False)
        finally:
            self._loading = False

    def _switch_profile(self, name: str):
        if self._loading or not name or name == self.cfg.active_profile:
            return
        self.cfg.active_profile = name
        self._load_profile_into_ui()
        self.c.apply()

    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "لعبة جديدة", "اسم اللعبة:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self.cfg.profiles:
            QMessageBox.information(self, "موجودة", "فيه لعبة بنفس الاسم.")
            return
        base = self.cfg.profile
        # Start from the current game's region and look; glossary starts empty.
        self.cfg.profiles[name] = GameProfile(name=name, region=copy.deepcopy(base.region), text_mode=base.text_mode,
                                              split_speaker=base.split_speaker, sensitivity=base.sensitivity)
        self.cfg.active_profile = name
        self._load_profile_into_ui()
        self.c.apply()

    def _rename_profile(self):
        old = self.cfg.active_profile
        name, ok = QInputDialog.getText(self, "تسمية", "الاسم الجديد:", text=old)
        name = name.strip()
        if not ok or not name or name == old:
            return
        if name in self.cfg.profiles:
            QMessageBox.information(self, "موجودة", "فيه لعبة بنفس الاسم.")
            return
        p = self.cfg.profiles.pop(old)
        p.name = name
        self.cfg.profiles[name] = p
        self.cfg.active_profile = name
        self.c.cache.rename_profile(old, name)
        self._load_profile_into_ui()
        self.c.apply()

    def _delete_profile(self):
        if len(self.cfg.profiles) <= 1:
            QMessageBox.information(self, "لا يمكن", "لازم تبقى لعبة وحدة على الأقل.")
            return
        name = self.cfg.active_profile
        if QMessageBox.question(self, "حذف", f"حذف إعدادات «{name}»؟ (الترجمات المحفوظة تبقى)") != QMessageBox.Yes:
            return
        del self.cfg.profiles[name]
        self.cfg.active_profile = sorted(self.cfg.profiles)[0]
        self._load_profile_into_ui()
        self.c.apply()

    # ============================================================= glossary

    def _glossary_append(self, en: str, ar: str):
        row = self.glossary_table.rowCount()
        self.glossary_table.insertRow(row)
        en_item = QTableWidgetItem(en)
        en_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.glossary_table.setItem(row, 0, en_item)
        self.glossary_table.setItem(row, 1, QTableWidgetItem(ar))

    def _glossary_add(self):
        self.glossary_table.blockSignals(True)
        self._glossary_append("", "")
        self.glossary_table.blockSignals(False)
        row = self.glossary_table.rowCount() - 1
        self.glossary_table.editItem(self.glossary_table.item(row, 0))

    def _glossary_remove(self):
        rows = sorted({i.row() for i in self.glossary_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.glossary_table.removeRow(r)
        self._glossary_changed()

    def _glossary_changed(self, *_):
        terms = {}
        for r in range(self.glossary_table.rowCount()):
            en = self.glossary_table.item(r, 0)
            ar = self.glossary_table.item(r, 1)
            en_t = en.text().strip() if en else ""
            ar_t = ar.text().strip() if ar else ""
            if en_t and ar_t:
                terms[en_t] = ar_t
        if terms != self.cfg.profile.glossary:
            self._set_profile("glossary", terms, glossary=True)

    # ============================================================= actions

    def _toggle(self):
        if self.c.running:
            self.start_btn.setEnabled(False)
            self.c.stop()
        else:
            if self._save_timer.isActive():
                self._save_timer.stop()
                self._flush_apply()
            self.c.start()

    def _toggle_local(self, on: bool):
        self._set("local_overlay", on)
        if on:
            self.overlay.show()
        else:
            self.overlay.hide()

    def _pick_region(self):
        try:
            frame = self.c.grab_full_frame()
        except (CaptureError, EOFError) as exc:
            QMessageBox.warning(self, "تعذّر الالتقاط", str(exc))
            return
        dlg = RegionPicker(frame, self.cfg.profile.region, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg.profile.region = dlg.region()
            self._load_profile_into_ui()
            self._schedule_apply()

    def _test_key(self):
        key = self.key_edit.text().strip()
        self._set("deepl_api_key", key, engines=True)
        self.key_result.setText("جارٍ الاختبار…")
        self.c.test_deepl(key, lambda ok, msg: self.deepl_result.emit(ok, msg))

    def _on_deepl_result(self, ok: bool, msg: str):
        self.key_result.setText(msg)
        self.key_result.setStyleSheet(f"color: {LEVEL_COLORS['ok' if ok else 'error']};")

    def _correct(self, event: SubtitleEvent | None):
        if event is None or not event.sources:
            return
        # Edit the Arabic of each segment on its own line (speaker labels are not part of it).
        current = "\n".join(seg["text"] for seg in event.segments)
        dlg = CorrectionDialog(event.english, current, self)
        if dlg.exec() != QDialog.Accepted or not dlg.text():
            return
        targets = [t.strip() for t in dlg.text().split("\n") if t.strip()]
        if len(targets) == len(event.sources):
            pairs = list(zip(event.sources, targets))
        else:
            pairs = [(" ".join(event.sources), " ".join(targets))] if len(event.sources) == 1 else []
        if not pairs:
            QMessageBox.information(self, "تصحيح", f"اكتب {len(event.sources)} أسطر، سطر لكل جملة.")
            return
        for src, tgt in pairs:
            self.c.service.correct(src, tgt)
        self._on_status("حُفظ التصحيح. سيُستخدم في كل مرة تظهر هذه الجملة.", "ok")

    def _open_data_dir(self):
        path = str(data_dir())
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opening our own folder
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _show_stats(self):
        st = self.c.cache.stats(self.cfg.active_profile)
        QMessageBox.information(self, "الذاكرة",
                                f"جمل مترجمة محفوظة: {st['translations']}\nتصحيحاتك: {st['corrections']}")

    # ============================================================= signals

    def _on_status(self, text: str, level: str):
        color = LEVEL_COLORS.get(level, LEVEL_COLORS["info"])
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"padding: 6px; border-radius: 4px; background: #eceff1; color: {color}; font-weight: bold;")

    def _on_engines_message(self, text: str, level: str):
        if text:
            self._on_status(text, level)

    def _on_running(self, running: bool):
        self.start_btn.setEnabled(True)
        self.start_btn.setText("إيقاف" if running else "ابدأ")
        if self.cfg.local_overlay and running:
            self.overlay.show()

    def _on_subtitle(self, ev: SubtitleEvent):
        self._last_event = ev
        self.en_label.setText(ev.english)
        self.ar_label.setText(ev.arabic)
        origin = ORIGIN_NAMES.get(ev.origin, ev.origin)
        self.timing_label.setText(
            f"القراءة {ev.ocr_ms:.0f} ms · الترجمة {ev.translate_ms:.0f} ms ({origin}) · الإجمالي {ev.total_ms:.0f} ms")
        # Isolate the English so right-to-left layout doesn't move its punctuation.
        english = "\n".join(f"\u2066{line}\u2069" for line in ev.english.split("\n"))
        item = QListWidgetItem(f"{ev.arabic}\n{english}")
        item.setData(Qt.UserRole, ev)
        self.history.insertItem(0, item)
        while self.history.count() > 100:
            self.history.takeItem(self.history.count() - 1)
        if ev.crop is not None:
            pix = QPixmap.fromImage(bgr_to_qimage(ev.crop))
            self.crop_preview.setPixmap(pix.scaled(self.crop_preview.width() - 8, 120, Qt.KeepAspectRatio,
                                                   Qt.SmoothTransformation))

    def _on_hidden(self):
        pass

    def _on_geometry(self, frame):
        self.overlay.follow(frame.pic_left, frame.pic_top, frame.pic_width, frame.pic_height, frame.crop_top)

    def _on_clients(self, clients: list):
        tvs = [c for c in clients if c.get("client") == "tv"]
        others = len(clients) - len(tvs)
        if tvs:
            names = "، ".join(c.get("name") or c.get("address", "") for c in tvs)
            text = f"التلفزيون: متصل ✓ ({names})"
        else:
            text = "التلفزيون: غير متصل"
        if others:
            text += f" · متصفحات: {others}"
        self.tv_label.setText(text)

    def closeEvent(self, event):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush_apply()
        self.overlay.close()
        self.c.shutdown()
        super().closeEvent(event)


HELP_HTML = """
<div dir="rtl" style="font-size:14px; line-height:1.6">
<h2>طريقة التشغيل</h2>
<ol>
<li>وصّل الـ PS5 بالتلفزيون مثل العادة، والعب بحسابك الأساسي.</li>
<li>على اللابتوب شغّل <b>PS Remote Play</b> وادخل بحساب PSN <b>ثانوي</b>، واتصل بالـ PS5.
  خلّ نافذته ظاهرة على شاشة اللابتوب (لا تصغّرها ولا تغطيها بنافذة ثانية).</li>
<li>في PS Remote Play: الإعدادات ← جودة الفيديو ← الدقة <b>1080p</b> (أو 720p لو الشبكة ضعيفة).</li>
<li>في اللعبة شغّل الترجمة الإنجليزية (Subtitles) وكبّر حجمها لو فيه خيار.</li>
<li>في هذه الأداة: تبويب «منطقة الحوار» ← حدّد مكان الترجمة مرة وحدة لكل لعبة.</li>
<li>تبويب «الترجمة» ← أدخل مفتاح DeepL واضغط «اختبار».</li>
<li>افتح تطبيق PlayTranslate في التلفزيون، ويتصل بنفسه. ثم اضغط «ابدأ» هنا.</li>
</ol>
<h2>مشاكل شائعة</h2>
<ul>
<li><b>التلفزيون ما يتصل:</b> تأكد إن اللابتوب والتلفزيون على نفس الشبكة، ووافقت على «السماح» لما سألك جدار الحماية في ويندوز
  (الشبكات الخاصة). أو اكتب عنوان اللابتوب يدويًا في تطبيق التلفزيون.</li>
<li><b>الأداة ما تقرأ الترجمة:</b> عدّل المنطقة، وجرّب «لون الترجمة» أو حرّك «الحساسية». شوف صورة «آخر ما قرأته الأداة».</li>
<li><b>محرك القراءة RapidOCR بدل Windows OCR:</b> طبيعي لو ويندوز بالعربي بدون لغة إنجليزية. يشتغل ممتاز.
  لو تبي Windows OCR: الإعدادات ← الوقت واللغة ← اللغة والمنطقة ← إضافة لغة ← English (United States).</li>
<li><b>«انتهى رصيد DeepL»:</b> الجمل المحفوظة تستمر تشتغل، والجديدة تظهر بالإنجليزي أو بـ Argos لو مثبت، لين يتجدد الشهر.</li>
</ul>
<p>كل جملة تُترجم مرة وحدة وتنحفظ، فإعادة المشاهد ما تستهلك رصيد.</p>
</div>
"""
