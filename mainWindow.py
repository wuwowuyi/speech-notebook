from __future__ import annotations
from typing import *

import logging
import re
import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread
from PyQt6.QtGui import QIcon, QTextCursor, QAction, QKeySequence
from PyQt6.QtWidgets import QMainWindow, QToolBar, QStatusBar, QVBoxLayout, QWidget, QTextEdit, \
    QPushButton, QStackedLayout, QLabel, QFileDialog


# TODO:  connect clean-up code to the aboutToQuit() signal, instead of putting it in your application’s main() function
from audio_transcribe import AudioTranscriber


class MainWindow(QMainWindow):

    def __init__(self, config: Dict[str, ...]):
        super().__init__()
        self._init_configs(config)
        self._init_widgets()
        self._load_content()

    def _init_configs(self, config):
        # default file to save when the application is closed
        self.WORKSPACE_FILE = config.get('WORKSPACE_FILE', 'recordings.txt')
        self.INITIAL_SIZE = config.get('WINDOW_SIZE', (800, 500))
        self.FILE_FILTER = ("text/plain", "text/html")

        self.MESSAGES = {
            'modified': config.get('MESSAGE.CONTENT_MODIFIED', 'content modified'),
            'saved': config.get('MESSAGE.CONTENT_SAVED', 'content saved'),
            'to_record': config.get('MESSAGE.TO_RECORD_HINT', 'Press and hold to record'),
            'recording': config.get('MESSAGE.IN_PROGRESS_HINT', 'Recording and transcribing in process'),
            'to_finish': config.get('MESSAGE.TRANSCRIBE_TO_FINISH_HINT', 'Transcribing still in process, please wait ...'),
        }

    def _init_widgets(self):
        self.setWindowTitle("Speech Notebook")
        self.resize(*self.INITIAL_SIZE)

        # toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        # add buttons to toolbar
        open_action = QAction(QIcon("resources/folder-horizontal-open.png"), "&Open", self)
        open_action.triggered.connect(self.open_file)
        open_action.setShortcut(QKeySequence("Ctrl+o"))
        toolbar.addAction(open_action)

        self.save_action = QAction(QIcon("resources/disk-black.png"), "&Save", self)
        self.save_action.triggered.connect(self.save_file)
        self.save_action.setShortcut(QKeySequence("Ctrl+s"))
        self.save_action.setEnabled(False)
        self.isopenfile = False  # a flag used for updating status
        toolbar.addAction(self.save_action)
        self.filepath = ''  # path used last time a file was open or saved

        # status bar
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

        # config to support:
        # font size, font style
        self.text_edit = QTextEdit()
        self.stack_layout.addWidget(self.text_edit)
        self.text_edit.textChanged.connect(self.set_tosave_status)

        self.label = QLabel("Recording")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack_layout.addWidget(self.label)

        # set up the record button
        self.record_btn = QPushButton(QIcon('resources/speaker-volume.png'), self.MESSAGES['to_record'], self)
        self.main_layout.addWidget(self.record_btn)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setFixedHeight(50)
        self.transcribe_thread = None
        self.worker = None
        self.recording = False

    def _load_content(self):
        workspace_file = Path(self.WORKSPACE_FILE)
        if workspace_file.is_file():
            with open(workspace_file, 'r') as f:
                self.isopenfile = True
                self.text_edit.setText(f.read())

            # set cursor to end of content
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _write_back(self, text, html=False):
        if self.recording:
            self.text_edit.insertPlainText(text)
            return

        if not self.recording and html:
            self.text_edit.insertHtml(text)
            return

        # now insert to document which the cursor may have moved away
        current_pos = self.text_edit.textCursor().position()
        doc_html = self.text_edit.document().toHtml()
        to_finish_tag_idx = doc_html.index("<span style=")
        before_tag_html = doc_html[:to_finish_tag_idx]
        new_html = ''.join((before_tag_html, text, doc_html[to_finish_tag_idx:]))
        self.text_edit.setHtml(new_html)

        start = before_tag_html.index("</head><body")
        before_tag_text = re.sub("<[^>]+>", "", before_tag_html[start:])
        cursor = self.text_edit.textCursor()
        cursor.setPosition(current_pos + len(text) if current_pos > len(before_tag_text) else current_pos)
        self.text_edit.setTextCursor(cursor)

    def _enable_recording(self):
        self.record_btn.setEnabled(True)
        self.record_btn.setText(self.MESSAGES['to_record'])
        self._cleanup_tags()

    def _cleanup_tags(self):
        """remove to_finish tag"""
        cursor = self.text_edit.textCursor()
        current_pos = cursor.position()
        doc_html = self.text_edit.document().toHtml()

        to_finish_tag_idx = doc_html.index("<span style=")
        before_tag_html = doc_html[:to_finish_tag_idx]
        start = before_tag_html.index("</head><body")
        before_tag_text = re.sub("<[^>]+>", "", before_tag_html[start:])

        content = re.sub("<span style=.+</span>", "", doc_html)
        self.text_edit.setHtml(content)
        cursor.setPosition(current_pos - 3 if current_pos > len(before_tag_text) else current_pos)  # 3 is the length of '...'
        self.text_edit.setTextCursor(cursor)

    def start_recording(self):
        """Start recording voice. """

        logging.debug(f"start recording....{time.strftime('%X')}")
        self.stack_layout.setCurrentWidget(self.label)

        self.transcribe_thread = QThread()
        self.worker = AudioTranscriber()
        self.worker.moveToThread(self.transcribe_thread)

        self.transcribe_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.transcribe_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.transcribe_thread.finished.connect(self.transcribe_thread.deleteLater)

        self.worker.progress.connect(self._write_back)
        self.transcribe_thread.start()
        self.recording = True

        self.record_btn.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.record_btn.setText(self.MESSAGES['recording'])
        self.transcribe_thread.finished.connect(self._enable_recording)
        # do not disable the button here otherwise it would terminate the recording thread.

    def stop_recording(self):
        """Stop recording and insert transcribed text into editor. """
        self.recording = False
        if self.worker:
            self.worker.stop()

        self.stack_layout.setCurrentWidget(self.text_edit)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setText(self.MESSAGES['to_finish'])
        self.record_btn.setEnabled(False)

    def closeEvent(self, event):
        """Handle window close event. """
        super().closeEvent(event)
        with open(self.WORKSPACE_FILE, 'w') as f:
            f.write(self.text_edit.toPlainText())

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
        """Save content in editor to a file. """
        filename, _ = QFileDialog().getSaveFileName(self, "Save File", self.filepath)
        if filename:
            with open(filename, 'w+') as f:
                f.write(self.text_edit.toPlainText())

            if self.filepath != filename:
                self.filepath = filename
            self.statusBar().showMessage(self.MESSAGES['saved'])
            self.save_action.setEnabled(False)

    def set_tosave_status(self):
        """Update save button status and the message in the status bar in bottom. """
        if not self.isopenfile:
            self.statusBar().showMessage(self.MESSAGES['modified'])
            self.save_action.setEnabled(True)
        else:
            self.isopenfile = False  # clear the flag
            self.statusBar().clearMessage()
            self.save_action.setEnabled(False)
