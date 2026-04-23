# Pacing

API FastAPI pour récupérer des données de natation : **Omega** (omegatiming.com), **Extranat** (FFN) et **USA Swimming** (data.usaswimming.org, via script).

## Prérequis

- Python 3.10+
- Navigateur Chromium pour Playwright (Omega, USA Swimming)

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
```

Pour les **notebooks Jupyter** (`app/visualization/*.ipynb`) et tout import `services` depuis un noyau dont le répertoire courant n’est pas la racine du dépôt, exécuter **une fois** à la racine `Pacing/` :

```bash
pip install -e .
```

Cela enregistre le paquet `services` dans l’environnement Python courant. Les cellules du notebook appellent aussi `pacing_bootstrap.py` (détection du repo via le chemin du notebook ou le disque).

Pour le script USA Swimming, installer aussi :

```bash
pip install pandas
```

En cas d’erreur SSL (réseau d’entreprise, proxy) :

```bash
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

## Lancer l’API

À la racine du projet (Pacing/) :

```bash
uvicorn app.main:app --reload
```

L’API est disponible sur **http://127.0.0.1:8000**.

## Endpoints

| Méthode | Route | Description |
|--------|--------|-------------|
| GET | `/omega/pdfs` | Scrape tous les PDFs Omega (plage configurée), retourne la liste |
| GET | `/omega/pdfs/by-years?start_year=&end_year=` | Scrape les PDFs Omega pour la plage d’années, retourne la liste |
| GET | `/extranat/results` | Tous les résultats Extranat |
| GET | `/extranat/results/by-date?start_date=&end_date=` | Résultats Extranat entre deux dates |
| GET | `/extranat/results/by-type?type_competition=` | Résultats par type de compétition |

## USA Swimming (script)

Le module **USA Swimming** n’est pas exposé en endpoint. Il s’utilise en script pour télécharger les temps (FINA Times) depuis le Data Hub USA Swimming (Sisense), avec authentification Bearer.

1. **Première utilisation** : lancer le script pour ouvrir le navigateur, se connecter sur https://data.usaswimming.org, puis sauvegarder l’état de session (`state.json`) et capturer le token (`bearer_token.txt` dans `services/`).
2. **Téléchargement** : les données sont paginées, sauvegardées par compétition dans `data/raw/usaswimming/` (un fichier JSON par meet + `_index.json`).

```bash
python -m services.usaswimming_service
```

Fichiers utilisés (dans `services/`) : `state.json`, `bearer_token.txt`. Les modèles des enregistrements sont dans `app/models/models.py` (`NageurRecord`).

## Documentation interactive

- **Swagger UI** : http://127.0.0.1:8000/docs  
- **ReDoc** : http://127.0.0.1:8000/redoc  

## Structure

```
app/
├── main.py              # Point d’entrée FastAPI (Omega + Extranat)
├── routers/             # omega, extranat
├── models/              # competition, extranat_models, usaswimming_models
├── scripts/             # count_omega_pdfs_by_year
├── visualization/     # notebooks Jupyter (graphics, etc.)
└── data/                # omega/pdfs/, extranat/, usaswimming/
```

```
services/
└── ...                  # omega_service, extranat_service, usaswimming_service
```

Données générées (ignorées par git) : `data/raw/` et `data/processed/`.