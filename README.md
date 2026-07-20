# Pacing

Application d’analyse du **pacing** et des performances en natation, à partir de données **Extranat**, **Omega**, **FRM Natation** et **USA Swimming**.

## À quoi sert ce projet ?

Pacing permet d’explorer des chronos et des splits, de comparer des nageurs et de visualiser le rythme de course (pacing, couloirs de performance, distributions de temps, etc.) sur des compétitions françaises, marocaines et américaines.

## Fonctionnalités principales

- **Interface desktop (Flet)** : recherche des nageurs selon le nom, le prénom ou l’année de naissance, filtres par épreuve, graphiques interactifs, couloirs de performance.
- **API FastAPI** (`app/main.py`) : endpoints pour Extranat, Omega et USA Swimming.
- **Notebooks Jupyter** : analyses et graphiques reproductibles (`app/visualization/`).

## Architecture (services/)

| Couche | Modules |
|--------|---------|
| Config / domaine | `paths.py`, `settings.py`, `normalize.py`, `scope.py`, `graph_catalog.py` |
| Données / ingestion | `*_data_loader.py`, `extranat_service.py`, `extranat_http.py`, `extranat_parse.py`, `extranat_results.py`, `extranat_competitions.py` |
| Analytics | `corridor_data.py`, `graph_compute.py` |
| Rendu / plots | `rendering/`, `graph_plots.py` (`GraphPlotsMixin`), `graph_desktop.py` |
| Application | `app_service.py` (façade UI), `use_cases.py`, `graph_service.py` (orchestration) |
| Présentation | `desktop_flet.py` + mixins (prefetch, registry, corridor, heatmap, handlers) → `PacingAppService` |

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
pip install -r requirements.txt
playwright install chromium
```

## Dépendances principales

| Catégorie | Paquets | Usage |
|-----------|---------|-------|
| API | `fastapi`, `uvicorn`, `pydantic` | Serveur REST |
| Scraping | `requests`, `beautifulsoup4`, `playwright` | Extranat, Omega, USA Swimming |
| Données | `pandas`, `pyarrow`, `numpy` | DataFrames, cache Parquet |
| Visualisation | `matplotlib`, `seaborn` | Graphiques (`services/rendering`, `graph_service`) |
| Interfaces | `flet` | Application desktop |
| Notebooks | `jupyter`, `notebook`, `ipykernel` | Analyses dans `app/visualization/` |

## Utilisation

Toutes les commandes ci-dessous s’exécutent depuis la racine du projet.

### API FastAPI

```bash
uvicorn app.main:app --reload
```

- Doc interactive Swagger : [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Prototype métier : `/api/v1/pays`, `/api/v1/nageur/recherche`, `/api/v1/couloir`, `/api/v1/comparaison`
- Contrat JSON : `docs/api_contract.md`

### Scripts et services (`services/`)

| Script | Commande | Rôle |
|--------|----------|------|
| Cache Parquet USA Swimming | `python services/build_usaswimming_parquet_cache.py [--years 2023 2024]` | Convertit les JSON annuels en Parquet |
| Scraping Extranat | `python services/extranat_service.py` | Récupère les résultats depuis extranat.ffnatation.fr |
| Scraping Omega | `python -m services.omega_service` | Télécharge les PDF « Total Ranking » depuis omegatiming.com |
| Scraping USA Swimming | `python services/usaswimming_service.py` | Interroge l’API Sisense (token requis) |

Les modules `services/*_data_loader.py` sont importés par les interfaces ; ils ne sont en général pas lancés directement.

## Structure des dossiers

```
Pacing/
├── app/
│   ├── interfaces/       # UI desktop (Flet) et helpers
│   ├── models/           # Modèles Pydantic / structures de données
│   ├── routers/          # Routes FastAPI
│   ├── scripts/          # Prétraitements (Extranat, FRM Natation, USA Swimming)
│   ├── visualization/    # Notebooks Jupyter
│   └── main.py           # Point d'entrée FastAPI
├── data/
│   ├── raw/              # Données brutes (scraping)
│   │   ├── extranat/
│   │   ├── omega/        # PDFs par année sous pdfs/
│   │   └── usaswimming/
│   └── processed/        # JSON/HTML normalisés, caches Parquet
│       ├── extranat/competitions_per_type/
│       ├── frmnatation/html_results/   # Résultats marocains (HTML → JSON)
│       └── usaswimming/                # JSON par année + _parquet_cache/
├── docs/                 # Rapports, captures d'écran
├── services/             # Cœur métier : scraping, loaders, graphiques, couloirs
│   ├── corridor_data.py              # Préparation des couloirs de performance
│   ├── graph_service.py              # Tous les graphiques matplotlib
│   ├── *_data_loader.py              # Chargement JSON/Parquet → DataFrame
│   ├── extranat_service.py           # Scraping Extranat
│   ├── omega_service.py              # Scraping Omega (PDF)
│   └── usaswimming_service.py        # Scraping API USA Swimming
└── requirements.txt
```

## Captures d'écran

Captures déposées dans [`docs/screenshots/`](docs/screenshots/) (desktop, notebooks).
