import logging
import sys

from PyQt6.QtWidgets import QApplication

from mainWindow import MainWindow


def main():
    logging.basicConfig(filename='speech_notebook.log', level=logging.DEBUG)
    app = QApplication(sys.argv)
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
