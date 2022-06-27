import logging
import sys

from PyQt6.QtWidgets import QApplication, QStyleFactory

from mainWindow import MainWindow


def main():
    logging.basicConfig(filename='speech_notebook.log', level=logging.DEBUG)
    logging.debug("\n\n")
    logging.debug("*" * 100)

    app = QApplication(sys.argv)
    if 'Fusion' in QStyleFactory.keys():
        app.setStyle('Fusion')  # Fusion is available on Windows, Mac, and Linux.

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    # TODO: load from a config file
    # credentials = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    # if not credentials:
    #     print('Must define environment variable GOOGLE_APPLICATION_CREDENTIALS')
    #     sys.exit(-1)

    main()
