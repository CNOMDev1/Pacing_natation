"""Package services : importer explicitement les modules nécessaires.

Exemples : ``from services.graph_service import ServiceGraphe``,
``from services.omega_service import ...``. Ne pas regrouper ici des imports
qui tirent des dépendances optionnelles (ex. Playwright), pour éviter de les
charger à chaque sous-module.
"""
