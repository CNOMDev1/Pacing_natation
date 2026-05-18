# Pacing

Application d’analyse du **pacing** et des performances en natation, à partir de données **Extranat**, **Omega** et **USA Swimming**.

## À quoi sert ce projet ?

Pacing permet d’explorer des chronos et des splits, de comparer des nageurs et de visualiser le rythme de course (pacing, couloirs de performance, distributions de temps, etc.) sur des compétitions françaises et américaines.

## Fonctionnalités principales

- **Interface desktop (Flet)** : recherche des nageurs selon le nom, le prénom ou l’année de naissance, filtres par épreuve, graphiques interactifs, couloirs de performance.
- **Interface web test (Streamlit)** : mêmes familles de graphiques dans le navigateur.
- **Notebooks Jupyter** : analyses et graphiques reproductibles (`app/visualization/`).

## Prérequis

- **Python 3.10+**
- **Chromium** (Playwright), pour certains scrapings
- Données déjà présentes ou à générer dans `data/` 

## Installation

À la racine du dépôt (`Pacing/`) :

```bash
python -m venv .venv
source .venv/bin/activate   
pip install -r requirements.txt
playwright install chromium
```

## Utilisation

Toutes les commandes ci-dessous s’exécutent depuis la racine du projet.

### Interfaces

| Interface | Commande |
|-----------|----------|
| Desktop | `python app/interfaces/desktop_flet.py` |
| Web | `streamlit run app/interfaces/web_streamlit.py` |
| Notebooks | `jupyter notebook app/visualization/` |

## Captures d'écran

Captures déposées dans [`docs/screenshots/`](docs/screenshots/) (desktop, Streamlit, notebooks).
