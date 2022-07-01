import logging
import os.path
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QStyleFactory

from mainWindow import MainWindow


CONFIG_FILE = 'config.txt'  # configuration file
LOG_FILE = 'speech_notebook.log'


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

    # set the GOOGLE_APPLICATION_CREDENTIALS environment variable
    google_service_account_key = config.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    if google_service_account_key is None:
        print("Must provide path to the JSON file that contains your Google service account key.")
        sys.exit(-1)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = google_service_account_key

    if os.environ.get('DEBUG', 'False').lower() == 'true':
        logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG)
        logging.debug("\n *" * 100)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("resources/app-icon.png"))
    if 'Fusion' in QStyleFactory.keys():
        app.setStyle('Fusion')  # Fusion is available on Windows, Mac, and Linux.

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

