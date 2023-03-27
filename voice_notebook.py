import logging
import os.path
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QStyleFactory

from mainwindow import MainWindow


CONFIG_FILE = 'config.txt'  # configuration file
LOG_FILE = 'voice_notebook.log'


def main():
    # load configurations
    config = {}
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                if line.startswith('#'):
                    continue
                line = line.strip()
                if not line:
                    continue
                if '#' in line:
                    line, _ = line.split('#', 1)  # remove trailing comment.
                if '=' not in line:
                    raise ValueError(f"Invalid config item read: {line}")
                key, value = line.split('=', 1)
                config[key.strip().upper()] = value.strip()

    if os.environ.get('PYTHONASYNCIODEBUG', '0') == '1':
        logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG)
        logging.debug("\n" + "*" * 100)  # to separate from previous log

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("resources/app-icon.png"))
    if 'Fusion' in QStyleFactory.keys():
        app.setStyle('Fusion')  # Fusion is available on Windows, Mac, and Linux.

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

