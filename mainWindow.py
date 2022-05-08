import sys
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QTextCursor, QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QMainWindow, QToolBar, QStatusBar, QVBoxLayout, QWidget, QTextEdit, \
    QPushButton, QStackedLayout, QLabel


class MainWindow(QMainWindow):

    # default file to save when the application is closed
    WORKSPACE_FILE = 'recordings.txt'
    INITIAL_SIZE = (800, 500)

    def __init__(self):
        super(MainWindow, self).__init__()
        self.setWindowTitle("Speech To Text")
        self.resize(*self.INITIAL_SIZE)

        # toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        # add buttons to tool bar
        save_action = QAction(QIcon("resources/disk-black.png"), "&Save", self)
        save_action.triggered.connect(self.save_file)
        save_action.setShortcut(QKeySequence("Ctrl+s"))
        toolbar.addAction(save_action)

        open_action = QAction(QIcon("resources/folder-horizontal-open.png"), "&Open", self)
        open_action.triggered.connect(self.open_file)
        open_action.setShortcut(QKeySequence("Ctrl+o"))
        toolbar.addAction(open_action)

        # conf_action = QAction(QIcon("resources/wrench-screwdriver.png"), "&Config", self)
        # conf_action.triggered.connect(self.config)
        # toolbar.addAction(conf_action)

        # status bar
        # self.setStatusBar(QStatusBar(self))

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
                self.text_edit.setText(f.read())
            # set cursor to end of content
            self.text_edit.moveCursor(QTextCursor.MoveOperation.End)

    def start_recording(self):
        self.stack_layout.setCurrentWidget(self.label)

    def stop_recording(self):
        self.text_edit.insertPlainText("hello world")
        self.stack_layout.setCurrentWidget(self.text_edit)

    def closeEvent(self, event):
        super().closeEvent(event)
        with open(self.WORKSPACE_FILE, 'w') as f:
            f.write(self.text_edit.toPlainText())

    def open_file(self):
        print('saved')

    def save_file(self):
        print('opened')

    def config(self):
        pass


app = QApplication(sys.argv)

window = MainWindow()
window.show()

app.exec()