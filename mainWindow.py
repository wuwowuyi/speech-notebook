import logging
import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThread
from PyQt6.QtGui import QIcon, QTextCursor, QAction, QKeySequence, QCursor
from PyQt6.QtWidgets import QMainWindow, QToolBar, QStatusBar, QVBoxLayout, QWidget, QTextEdit, \
    QPushButton, QStackedLayout, QLabel, QFileDialog


# TODO:  connect clean-up code to the aboutToQuit() signal, instead of putting it in your application’s main() function
from audio_transcribe import AudioTranscriber


class MainWindow(QMainWindow):

    # default file to save when the application is closed
    WORKSPACE_FILE = 'recordings.txt'
    INITIAL_SIZE = (800, 500)
    FILE_FILTER = ("text/plain", "text/html")

    MESSAGES = {
        'to_save': 'content modified',
        'saved': 'content saved',
        'to_record': 'Press and hold to record',
        'recording': 'Recording and transcribing in process',
        'to_finish': 'Transcribing in process, please wait ...'
    }

    # configs to support
    # - language
    # - editor font size, font style
    #

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle("Voice Notebook")
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

        # conf_action = QAction(QIcon("resources/wrench-screwdriver.png"), "&Config", self)
        # conf_action.triggered.connect(self.config)
        # toolbar.addAction(conf_action)

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

        self.transcribe_thread = None
        self.worker = None
        self.record_btn = QPushButton(QIcon('resources/speaker-volume.png'), self.MESSAGES['to_record'], self)
        self.main_layout.addWidget(self.record_btn)
        self.record_btn.pressed.connect(self.start_recording)
        self.record_btn.released.connect(self.stop_recording)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setFixedHeight(50)

        self.load_content()

    def load_content(self):
        workspace_file = Path(self.WORKSPACE_FILE)
        if workspace_file.is_file():
            with open(workspace_file, 'r') as f:
                self.isopenfile = True
                self.text_edit.setText(f.read())

            # set cursor to end of content
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _write_back(self, content, insert_pos=-1):
        if insert_pos == -1:  # insert to where the cursor is
            self.text_edit.insertPlainText(content)
            return

        cursor = self.text_edit.textCursor()
        current_pos = cursor.position()
        if current_pos == insert_pos:
            self.text_edit.insertPlainText(content)
        else:
            after = repr(self.text_edit.document)[insert_pos:]
            cursor.setPosition(insert_pos)
            cursor.insertText(content)
            cursor.insertText(after)

    def enable_recording(self):
        self.record_btn.setEnabled(True)
        self.record_btn.setText(self.MESSAGES['to_record'])

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

        self.record_btn.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.record_btn.setText(self.MESSAGES['recording'])
        self.transcribe_thread.finished.connect(self.enable_recording)
        # do not disable the button here otherwise it would terminate the recording thread.

    def stop_recording(self):
        """Stop recording and insert transcribed text into editor. """
        if self.worker:
            self.worker.stop(self.text_edit.textCursor().position())

        self.stack_layout.setCurrentWidget(self.text_edit)
        self.record_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record_btn.setText(self.MESSAGES['to_finish'])
        self.record_btn.setEnabled(False)

    def closeEvent(self, event):
        """Handle window close event. """
        super().closeEvent(event)
        with open(self.WORKSPACE_FILE, 'w') as f:
            f.write(self.text_edit.toPlainText())

    def config(self):
        pass

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
            self.statusBar().showMessage(self.MESSAGES['to_save'])
            self.save_action.setEnabled(True)
        else:
            self.isopenfile = False  # clear the flag
            self.statusBar().clearMessage()
            self.save_action.setEnabled(False)


