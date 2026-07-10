from PySide6.QtGui import QFont, QFontDatabase

def system_monospace_font(point_size: int | None = None) -> QFont:
    font = QFontDatabase.systemFont(
        QFontDatabase.SystemFont.FixedFont
    )
    if point_size is not None:
        font.setPointSize(point_size)
    return font
