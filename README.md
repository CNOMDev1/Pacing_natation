# Pacing

API FastAPI pour récupérer des données de natation : **Omega** (omegatiming.com) et **Extranat** (FFN).

## Prérequis

- Python 3.10+
- Navigateur Chromium pour Playwright (Omega)

## Installation

```bash
pip install -r requirements.txt
playwright install chromium
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

## Documentation interactive

- **Swagger UI** : http://127.0.0.1:8000/docs  
- **ReDoc** : http://127.0.0.1:8000/redoc  

## Structure

```
app/
├── main.py           # Point d’entrée FastAPI
├── routers/          # Omega, Extranat
├── services/         # Scraping Omega, Extranat
├── models/           # Modèles (ex. types de compétition)
├── scripts/          # Scripts (ex. comptage PDFs par année)
└── data/             # Données scrapées (omega, extranat)
```

