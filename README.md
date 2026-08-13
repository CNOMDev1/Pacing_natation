# Pacing

Application d’analyse du **pacing** et des performances en natation, à partir de données **Extranat**, **Omega**, **FRM Natation** et **USA Swimming**.

## À quoi sert ce projet ?

Pacing permet d’explorer des chronos et des splits, de comparer des nageurs et de visualiser le rythme de course (pacing, couloirs de performance, distributions de temps, etc.) sur des compétitions françaises, marocaines et américaines.

## Architecture

```
pacing/
├── config/        # Chemins + settings (PACING_*)
├── domain/        # Normalisation, labels nage, schémas
├── ingestion/     # Scraping + ETL par source
├── data/          # Loaders / repositories
├── analytics/     # Calculs purs (sans matplotlib)
├── rendering/     # Matplotlib pur
├── application/   # Use cases (BuildCorridorChart, PrefetchGraphs, ServiceGraphe)
├── api/           # FastAPI
└── ui/            # Desktop Flet + web NiceGUI + DearPyGUI + widgets
```

Principe : **calcul sans matplotlib**, **rendu sans logique métier lourde**, **UI sans scraping**.

Le dossier `services/` conserve le cœur API legacy (`api_core`, `app_service`) et les secrets locaux.

## Tests

```bash
PYTHONPATH=. pytest tests/ -q
```

## Prérequis

- **Python 3.10+**
- **Chromium** (Playwright), pour les scrapings Omega et le token USA Swimming
- Données déjà présentes ou à générer dans `data/`

## Installation

À la racine du dépôt (`Pacing/`) :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
# ou : pip install -r requirements.txt
playwright install chromium
```

## Dépendances principales

| Catégorie | Paquets | Usage |
|-----------|---------|-------|
| API | `fastapi`, `uvicorn`, `pydantic` | Serveur REST |
| Scraping | `requests`, `beautifulsoup4`, `playwright` | Extranat, Omega, USA Swimming |
| Données | `pandas`, `pyarrow`, `numpy` | DataFrames, cache Parquet |
| Visualisation | `matplotlib`, `seaborn` | Graphiques |
| Interfaces | `flet` | Application desktop |
| Notebooks | `jupyter`, `notebook`, `ipykernel` | Analyses dans `notebooks/` |

## Utilisation

### Interfaces

| Interface | Commande |
|-----------|----------|
| Desktop (Flet) | `python -m pacing.ui.desktop.app` (ou `pacing-desktop`) |
| Web (NiceGUI) | `python -m pacing.ui.web.app` (ou `pacing-web`) — API FastAPI requise |
| Desktop (DearPyGUI) | `python -m pacing.ui.dearpygui.app` (ou `pacing-dpg`) — API FastAPI requise |
| iPad / macOS (SwiftUI) | `open ios/PacingApp/PacingApp.xcodeproj` — voir `docs/ios_mac_exploration_5_5.md` |
| API | `uvicorn pacing.api.main:app --reload` |
| Notebooks | `jupyter notebook notebooks/` |

Variables utiles : `PACING_API_BASE_URL` (défaut `http://127.0.0.1:8000`), `PACING_WEB_PORT` (défaut `8080`).

- Doc interactive Swagger : [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Prototype métier : `/api/v1/pays`, `/api/v1/nageur/recherche`, `/api/v1/couloir`, `/api/v1/comparaison`
- Contrat JSON : `docs/api_contract.md`
- Exploration iOS/macOS (§5.5) : `docs/ios_mac_exploration_5_5.md`

### Ingestion & ETL

| Script | Commande |
|--------|----------|
| Scraping Extranat | `python -m pacing.ingestion.extranat.service` |
| Scraping Omega | `python -m pacing.ingestion.omega.service` |
| Scraping USA Swimming | `python -m pacing.ingestion.usaswimming.service` |
| Token USA Swimming | `python -m pacing.ingestion.usaswimming.get_token` |
| Prétraitement Extranat | `python -m pacing.ingestion.extranat.preprocessing` |
| Prétraitement FRM | `python -m pacing.ingestion.frmnatation.preprocessing` |
| Prétraitement USA | `python -m pacing.ingestion.usaswimming.preprocessing` |
| Cache Parquet USA | via `UsaswimmingCompetitionsDataLoader.build_parquet_cache()` |

### Settings prefetch (`PACING_*`)

Exemples : `PACING_CORRIDOR_CHART_PREFETCH_LIMIT`, `PACING_HEATMAP_PREFETCH_SWIMMER_LIMIT`, `PACING_ENABLE_CORRIDOR_CHART_PREFETCH`. Voir `pacing/config/settings.py`.

## Structure des dossiers

```
Pacing/
├── pacing/               # Package applicatif (architecture en couches)
├── services/             # Cœur API legacy (`api_core`, `app_service`) + secrets locaux
├── notebooks/            # Jupyter notebooks d'analyse
├── data/                 # raw / processed / exports (hors git)
├── ios/                 # Prototype SwiftUI iPad/macOS (§5.5)
├── docs/
├── pyproject.toml
└── requirements.txt
```
