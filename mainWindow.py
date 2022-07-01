from __future__ import annotations
from typing import *

import logging
import re
import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread, QTimer
from PyQt6.QtGui import QIcon, QTextCursor, QAction, QKeySequence, QFont
from PyQt6.QtWidgets import QMainWindow, QToolBar, QStatusBar, QVBoxLayout, QWidget, QTextEdit, \
    QPushButton, QStackedLayout, QLabel, QFileDialog

from Transcriber import AudioTranscriber


class MainWindow(QMainWindow):

    def __init__(self, config: Dict[str, str]):
        super().__init__()
        self._init_configs(config)
        self._init_widgets()
        self._load_content()
        self.config = config

    def _init_configs(self, config):
        """Read configurations from the config file.
        Use the default value if a configuration item is invalid or not set. """

        # default file to save when the application is closed
        filename = config.pop('WORKSPACE_FILE', 'recordings.txt').lower()
        if not filename.endswith('.txt'):  # only allow .txt file
            self.WORKSPACE_FILE = '.'.join((re.sub('\.', '-', filename), 'txt'))
        else:
            self.WORKSPACE_FILE = filename

        # initial window size
        initial_size = config.pop('WINDOW_SIZE', "800,600")
        try:
            width, height = initial_size.split(',', 1)
            self.INITIAL_SIZE = (int(width.strip()), int(height.strip()))
        except ValueError as ve:
            logging.warning("Invalid window size", ve)
            self.INITIAL_SIZE = (800, 600)  # use

        self.FILE_FILTER = ("text/plain", "text/html")

        # init font size
        try:
            font_size = int(config.pop('FONT_SIZE', 16))
            if font_size > 30 or font_size < 8:
                raise ValueError("font size must be between 8 and 30.")
            self.FONT_SIZE = font_size
        except ValueError as ve:
            logging.warning("Invalid font size", ve)
            self.FONT_SIZE = 16

        self.MESSAGES = {
            'modified': config.pop('MESSAGE.CONTENT_MODIFIED', 'content modified'),
            'saved': config.pop('MESSAGE.CONTENT_SAVED', 'content saved'),
            'to_record': config.pop('MESSAGE.TO_RECORD_HINT', 'Press and hold to record'),
            'recording': config.pop('MESSAGE.IN_PROGRESS_HINT', 'Recording and transcribing in process'),
            'to_finish': config.pop('MESSAGE.TRANSCRIBE_TO_FINISH_HINT', 'Transcribing still in process, please wait ...'),
            'recording': config.pop('MESSAGE.RECORDING', 'recording'),
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

        # main widget is the text editor.
        self.text_edit = QTextEdit()
        self.stack_layout.addWidget(self.text_edit)
        self.text_edit.textChanged.connect(self.set_tosave_status)

        # label widget covering the text editor when recording.
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack_layout.addWidget(self.label)
        font = QFont()
        font.setPointSize(20)
        self.label.setFont(font)
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_label)

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

        font = QFont()
        font.setPointSize(self.FONT_SIZE)
        self.text_edit.setFont(font)  # zoom throws warnings after setting font

    def _load_content(self) -> None:
        """Load auto saved content into the text editor on application start. """
        workspace_file = Path(self.WORKSPACE_FILE)
        if workspace_file.is_file():
            with open(workspace_file, 'r') as f:
                self.isopenfile = True
                self.text_edit.setText(f.read())

            # set cursor to end of content
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _write_back(self, text: str, html: bool = False) -> None:
        """
        For transcriber to write back transcribed text into the text editor.

        :param text: transcribed text to be inserted into text editor.
        :param html: is the text HTML or plain text?
        """
        if self.recording:
            self.text_edit.insertPlainText(text)
            return

        # This is for the transcriber to insert a to-finish placeholder tag.
        # so that later the transcribed text can be inserted into the right place.
        if not self.recording and html:
            self.text_edit.insertHtml(text)
            return

        # When user releases the recording button and returns to the text editor,
        # the cursor could have moved away from where the transcribed text should be inserted into
        # when this method is called.
        # We want to insert into the right place while preserving the cursor position.
        current_pos = self.text_edit.textCursor().position()
        doc_html = self.text_edit.document().toHtml()
        try:
            to_finish_tag_idx = doc_html.index("<span style=")
            before_tag_html = doc_html[:to_finish_tag_idx]
            new_html = ''.join((before_tag_html, text, doc_html[to_finish_tag_idx:]))
            self.text_edit.setHtml(new_html)
        except ValueError as ve:
            logging.error(f"cannot locate the to-finish tag to insert transcribed text: {ve}")
            self.text_edit.insertPlainText(text)  # insert where the cursor is
            return

        # now try to set the cursor back to the original place
        try:
            start = before_tag_html.index("</head><body")
            before_tag_text = re.sub("<[^>]+>", "", before_tag_html[start:])
            cursor = self.text_edit.textCursor()
            cursor.setPosition(current_pos + len(text) if current_pos > len(before_tag_text) else current_pos)
            self.text_edit.setTextCursor(cursor)
        except ValueError as ve:
            logging.error(f"cannot locate the start of HTML content. {ve}")
            pass

    def _enable_recording(self) -> None:
        """Called when the transcriber has transcribed all the voice data and is terminating. """
        self._cleanup_tags()
        self.record_btn.setEnabled(True)
        self.record_btn.setText(self.MESSAGES['to_record'])

    def _cleanup_tags(self, preserve_cursor: bool = True) -> None:
        """Remove the to-finish tag for the transcriber.
        There should only be at most one such tag at a time.
        """

        # Remove the to-finish tag
        cursor = self.text_edit.textCursor()
        current_pos = cursor.position()
        doc_html = self.text_edit.document().toHtml()
        content = re.sub("<span style=.+</span>", "", doc_html)
        self.text_edit.setHtml(content)  # cursor is at beginning after setting the content.

        # try to preserve the cursor position
        if preserve_cursor:
            try:
                to_finish_tag_idx = doc_html.index("<span style=")
                before_tag_html = doc_html[:to_finish_tag_idx]
                start = before_tag_html.index("</head><body")
                before_tag_text = re.sub("<[^>]+>", "", before_tag_html[start:])

                # 3 is the length of '...'
                cursor.setPosition(current_pos - 3 if current_pos > len(before_tag_text) else current_pos)
                self.text_edit.setTextCursor(cursor)
            except ValueError:  # tag not found
                pass

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
        self.recording = True

        self.record_btn.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.record_btn.setText(self.MESSAGES['recording'])
        self.transcribe_thread.finished.connect(self._enable_recording)
        # do not disable the button here otherwise it would terminate the recording thread.

        # setup a timer to show recording duration
        self.label.setText(f"{self.MESSAGES['recording']} 0 seconds")
        self.timer.start(1000)

    def stop_recording(self):
        """Stop recording and insert transcribed text into editor. """
        self.recording = False
        self.timer.stop()
        if self.worker:
            self.worker.stop()

        self.stack_layout.setCurrentWidget(self.text_edit)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setText(self.MESSAGES['to_finish'])
        self.record_btn.setEnabled(False)

    def _update_label(self):
        text = self.label.text()
        start = len(self.MESSAGES['recording']) + 1
        duration = int(text[start:].split(' ', 1)[0])
        self.label.setText(f"{self.MESSAGES['recording']} {duration + 1} seconds")

    def closeEvent(self, event):
        """Handle window close event. """
        super().closeEvent(event)
        self._cleanup_tags(False)  # clean up tags just in case.
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
