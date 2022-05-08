import sys
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QTextCursor, QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QMainWindow, QToolBar, QStatusBar, QVBoxLayout, QWidget, QTextEdit, \
    QPushButton, QStackedLayout, QLabel, QFileDialog


class MainWindow(QMainWindow):

    # default file to save when the application is closed
    WORKSPACE_FILE = 'recordings.txt'
    INITIAL_SIZE = (800, 500)
    FILE_FILTER = ("text/plain", "text/html")

    MESSAGES = {
        'to_save': 'content modified',
        'saved': 'content saved'
    }

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle("Speech To Text")
        self.resize(*self.INITIAL_SIZE)

        # toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        # add buttons to tool bar
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
        self.filepath = ''

        # conf_action = QAction(QIcon("resources/wrench-screwdriver.png"), "&Config", self)
        # conf_action.triggered.connect(self.config)
        # toolbar.addAction(conf_action)

        # status bar
        self.setStatusBar(QStatusBar(self))

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

        record_btn = QPushButton(QIcon('resources/speaker-volume.png'), 'Hold to record', self)
        self.main_layout.addWidget(record_btn)
        record_btn.pressed.connect(self.start_recording)
        record_btn.released.connect(self.stop_recording)

        self.load_content()

    def load_content(self):
        workspace_file = Path(self.WORKSPACE_FILE)
        if workspace_file.is_file():
            with open(workspace_file, 'r') as f:
                self.isopenfile = True
                self.text_edit.setText(f.read())

            # set cursor to end of content
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def start_recording(self):
        """Start recording voice. """
        self.stack_layout.setCurrentWidget(self.label)

    def stop_recording(self):
        """Stop recording and insert voice to text into editor. """
        self.text_edit.insertPlainText("hello world")
        self.stack_layout.setCurrentWidget(self.text_edit)

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


app = QApplication(sys.argv)

window = MainWindow()
window.show()

sys.exit(app.exec())