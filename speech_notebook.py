import logging
import os.path
import sys

from PyQt6.QtWidgets import QApplication, QStyleFactory

from mainWindow import MainWindow


CONFIG_FILE = 'config.txt'


def main():
    logging.basicConfig(filename='speech_notebook.log', level=logging.DEBUG)
    logging.debug("\n\n")
    logging.debug("*" * 100)

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
                if '=' not in line:
                    raise ValueError(f"Invalid config item read: {line}")
                key, value = line.split('=', 1)
                config[key.strip().upper()] = value.strip()

    app = QApplication(sys.argv)
    if 'Fusion' in QStyleFactory.keys():
        app.setStyle('Fusion')  # Fusion is available on Windows, Mac, and Linux.

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    # credentials = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    # if not credentials:
    #     print('Must define environment variable GOOGLE_APPLICATION_CREDENTIALS')
    #     sys.exit(-1)
    main()

