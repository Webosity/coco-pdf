import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from coco_pdf import asset
from coco_pdf.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Coco PDF")
    app.setOrganizationName("Digital Rhapsody")
    app.setWindowIcon(QIcon(str(asset("coco-pdf.ico"))))
    # French labels for Qt's standard buttons and dialogs (Cancel, Yes/No, file dialogs).
    translator = QTranslator(app)
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(QLocale.Language.French), "qtbase", "_", translations):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    # The file passed by Windows Explorer ("Open with" / double-click) arrives as the first argument.
    files = [arg for arg in sys.argv[1:] if arg.lower().endswith(".pdf")]
    if files:
        window.open_file(files[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
