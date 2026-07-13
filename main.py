"""
DemandFlow - Ponto de Entrada
Inicializa dependências e abre a janela principal.
"""
import sys
from pathlib import Path


# Garante que o pacote raiz está no path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QFont, QIcon

from infrastructure.repositories.sqlite_repository import SQLiteDemandRepository
from infrastructure.services.file_service import DemandFileService
from core.usecases.demand_usecases import DemandUseCases
from presentation.windows.main_window import MainWindow
from presentation.styles.stylesheet import get_stylesheet
from infrastructure.services.ai_service import create_ai_service

def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("DemandFlow")
    app.setApplicationName("App")
    # High-DPI
    #app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)

    # Ícone do app (janela/barra de tarefas)
    base_dir = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    app.setWindowIcon(QIcon(str(base_dir / "resources" / "icon.ico")))

    # Font padrão
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Diretórios de dados
    data_dir = Path.home() / ".demandflow"
    data_dir.mkdir(parents=True, exist_ok=True)

    db_path   = data_dir / "demandflow.db"
    files_dir = data_dir / "demandas"          # pasta raiz de todas as demandas
    files_dir.mkdir(parents=True, exist_ok=True)

    repo         = SQLiteDemandRepository(str(db_path))
    use_cases    = DemandUseCases(repo)
    file_service = DemandFileService(files_dir)

    settings    = QSettings("DemandFlow", "App")
    api_key     = settings.value("ai/api_key", "")
    provider    = settings.value("ai/provider", "gemini")
    ai_service  = create_ai_service(provider, api_key)

    app.setStyleSheet(get_stylesheet(dark=False))

    # Garante que toda demanda existente já tem sua pasta, renomeando se o
    # título mudou de'sde a última vez (evita criar pastas duplicadas).
    for d in use_cases.list_all():
        file_service.rename_demand_folder(d.id, d.title)

    window = MainWindow(use_cases, file_service, ai_service)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
