from __future__ import annotations

import logging
import time
from typing import *

from PyQt6.QtCore import QSize, Qt, QThread, QTimer
from PyQt6.QtGui import QIcon, QAction, QKeySequence, QFont
from PyQt6.QtWidgets import QMainWindow, QToolBar, QStatusBar, QVBoxLayout, QWidget, QTextEdit, \
    QPushButton, QStackedLayout, QLabel, QFileDialog

from transcriber import AudioTranscriber


CONFIG_FILE = 'config.txt'  # configuration file


class MainWindow(QMainWindow):
    MAX_FONT_SIZE = 30
    MIN_FONT_SIZE = 10

    def __init__(self, config: Dict[str, str]):
        super().__init__()
        self._window_config(config)
        self._init_widgets()
        self.config = config  # for transcriber
        self.transcribe_thread = None
        self.worker = None  # worker thread

    def _window_config(self, config: Dict[str, str]) -> None:
        """Read configurations from the config file.
        Use the default value if a configuration item is invalid or unset. """

        # initial window size
        initial_size = config.pop('WINDOW_SIZE', "800,600")
        try:
            width, height = initial_size.split(',', 1)
            self.INITIAL_SIZE = (int(width.strip()), int(height.strip()))
        except ValueError as ve:
            logging.warning("Invalid window size", ve)
            self.INITIAL_SIZE = (800, 600)  # use default

        self.FILE_FILTER = ("text/plain", )

        # init font size
        try:
            font_size = int(config.pop('FONT_SIZE', 16))
            if font_size > self.MAX_FONT_SIZE or font_size < self.MIN_FONT_SIZE:
                logging.warning(f"font size must be between {self.MIN_FONT_SIZE} and {self.MAX_FONT_SIZE}.")
                font_size = 16  # revert to default
            self.font_size = font_size
        except ValueError as ve:
            logging.warning("Invalid font size", ve)
            self.font_size = 16

        self.MESSAGES = {
            'modified': config.pop('MESSAGE.CONTENT_MODIFIED', 'content modified'),
            'saved': config.pop('MESSAGE.CONTENT_SAVED', 'content saved'),
            'to_record': config.pop('MESSAGE.TO_RECORD_HINT', 'Press and hold to record'),
            'to_finish': config.pop('MESSAGE.TRANSCRIBE_TO_FINISH_HINT',
                                    'Transcribing still in process, please wait ...'),
            'recording': config.pop('MESSAGE.RECORDING', 'Recording')
        }

    def _init_widgets(self):
        self.setWindowTitle("Voice Notebook")
        self.resize(*self.INITIAL_SIZE)

        # toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        # add buttons to toolbar
        # open file button
        open_action = QAction(QIcon("resources/folder-horizontal-open.png"), "&Open", self)
        open_action.triggered.connect(self.open_file)
        open_action.setShortcut(QKeySequence("Ctrl+o"))
        toolbar.addAction(open_action)

        # save button
        self.save_action = QAction(QIcon("resources/disk-black.png"), "&Save", self)
        self.save_action.triggered.connect(self.save_file)
        self.save_action.setShortcut(QKeySequence("Ctrl+s"))
        self.save_action.setEnabled(False)
        toolbar.addAction(self.save_action)
        self.isopenfile = False  # a flag used for updating status
        self.filepath = ''  # path used last time a file was open or saved

        # new file button
        self.new_action = QAction(QIcon("resources/add.png"), "&New", self)
        self.new_action.triggered.connect(self.new_file)
        self.new_action.setShortcut(QKeySequence("Ctrl+n"))
        toolbar.addAction(self.new_action)

        # decrease and increase font size buttons
        self.decrease_fz = QAction(QIcon("resources/decrease-font-size.png"), "&-font size", self)
        self.increase_fz = QAction(QIcon("resources/increase-font-size.png"), "&+font size", self)
        self.decrease_fz.triggered.connect(self.decrease_font_size)
        self.increase_fz.triggered.connect(self.increase_font_size)
        self.increase_fz.setShortcut(QKeySequence("Ctrl+="))
        self.decrease_fz.setShortcut(QKeySequence("Ctrl+-"))
        toolbar.addAction(self.decrease_fz)
        toolbar.addAction(self.increase_fz)

        # status bar near bottom of window
        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        status_bar.setFixedHeight(30)

        # layout
        self.main_layout = QVBoxLayout()
        self.stack_layout = QStackedLayout()
        self.main_layout.addLayout(self.stack_layout)
        widget = QWidget()
        widget.setLayout(self.main_layout)
        self.setCentralWidget(widget)

        # main widget is the text editor.
        self.text_edit = QTextEdit()
        self.stack_layout.addWidget(self.text_edit)
        self.text_edit.textChanged.connect(self.set_status_msg)

        # label widget covering the text editor when recording.
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack_layout.addWidget(self.label)
        font = QFont()
        font.setPointSize(20)
        self.label.setFont(font)
        self.timer = QTimer()  # timer to update the label
        self.timer.timeout.connect(self._update_label)

        # set up the record button
        self.record_btn = QPushButton(QIcon('resources/speaker-volume.png'),
                                      self.MESSAGES['to_record'], self)
        self.main_layout.addWidget(self.record_btn)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setFixedHeight(50)

        font = QFont()
        font.setPointSize(self.font_size)
        self.text_edit.setFont(font)  # zoom throws warnings after setting font

    def decrease_font_size(self):
        font = self.text_edit.font()
        intend_size = font.pointSize() - 2
        if intend_size >= self.MIN_FONT_SIZE:
            font.setPointSize(intend_size)
            self.text_edit.setFont(font)
            self.font_size = intend_size

    def increase_font_size(self):
        font = self.text_edit.font()
        intend_size = font.pointSize() + 2
        if intend_size <= self.MAX_FONT_SIZE:
            font.setPointSize(intend_size)
            self.text_edit.setFont(font)
            self.font_size = intend_size

    def _write_back(self, text: str) -> None:
        """
        For transcriber to write back transcribed text into the text editor.

        :param text: transcribed text to be inserted into text editor.
        """
        self.text_edit.insertPlainText(text)

    def _enable_recording(self) -> None:
        """Called after the transcriber has transcribed all the voice data and terminated. """
        self.stack_layout.setCurrentWidget(self.text_edit)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setEnabled(True)
        self.record_btn.setText(self.MESSAGES['to_record'])

    def start_recording(self):
        """Start recording voice. """

        logging.debug(f"start recording....{time.strftime('%X')}")
        self.stack_layout.setCurrentWidget(self.label)

        self.transcribe_thread = QThread()
        self.worker = AudioTranscriber(self.config)
        self.worker.moveToThread(self.transcribe_thread)

        self.transcribe_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.transcribe_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.transcribe_thread.finished.connect(self.transcribe_thread.deleteLater)
        self.worker.progress.connect(self._write_back)

        self.transcribe_thread.start()

        self.record_btn.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.record_btn.setText(self.MESSAGES['recording'])
        self.transcribe_thread.finished.connect(self._enable_recording)
        # do not disable the button here otherwise it would terminate the recording thread.

        # setup a timer to show recording duration
        self.label.setText(f"{self.MESSAGES['recording']} 0 seconds")
        self.timer.start(1000)

    def stop_recording(self):
        """Stop recording and insert transcribed text into editor. """
        self.timer.stop()
        if self.worker:
            self.worker.stop()

        self.record_btn.setText(self.MESSAGES['to_finish'])
        self.record_btn.setEnabled(False)

    def _update_label(self):
        """For timer to call to update during recording. """
        text = self.label.text()
        start = len(self.MESSAGES['recording']) + 1
        duration = int(text[start:].split(' ', 1)[0])
        self.label.setText(f"{self.MESSAGES['recording']} {duration + 1} seconds")

    def closeEvent(self, event):
        """Handle window close event. """
        super().closeEvent(event)
        if self.save_action.isEnabled():  # content is not saved
            self.save_file()

        saved = False  # font size config saved or not
        with open(CONFIG_FILE, 'r+') as f:  # save current font size
            lines = f.readlines()
            f.seek(0)
            for line in lines:
                if not line or not line.startswith('FONT_SIZE'):
                    f.write(line)
                else:
                    f.write(f"FONT_SIZE={self.font_size}\n")
                    saved = True
            if not saved:
                f.write(f"FONT_SIZE={self.font_size}")

    def open_file(self):
        """Open an existing text file and load its content into the editor. """
        dlg = QFileDialog()
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        dlg.setMimeTypeFilters(self.FILE_FILTER)

        if dlg.exec():
            filename = dlg.selectedFiles()
            if len(filename) > 0:
                self.filepath = filename[0]
                with open(filename[0], 'r') as f:
                    self.isopenfile = True
                    self.text_edit.setText(f.read())

    def save_file(self):
        """Save content in editor to file. """
        if self.filepath:  # save to the file which the content was loaded/saved.
            fname = self.filepath
        else:  # save into a new file
            fname, _ = QFileDialog.getSaveFileName(self, 'Save File')
        if fname:
            with open(fname, 'w') as f:
                f.write(self.text_edit.toPlainText() or '')
                self.filepath = fname
                self.statusBar().showMessage(self.MESSAGES['saved'])
                self.save_action.setEnabled(False)

    def new_file(self):
        if self.save_action.isEnabled():  # content is not saved
            self.save_file()

        self.filepath = ''
        self.text_edit.clear()
        self.save_action.setEnabled(False)
        self.statusBar().showMessage('')

    def set_status_msg(self):
        """Update save button status and the message in the status bar in bottom. """
        if not self.isopenfile:
            self.statusBar().showMessage(self.MESSAGES['modified'])
            self.save_action.setEnabled(True)
        else:
            self.isopenfile = False  # clear the flag
            self.statusBar().clearMessage()
            self.save_action.setEnabled(False)
