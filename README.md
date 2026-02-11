# Extranat - Recuperation des competitions FFN

Scripts Python pour recuperer les donnees des competitions de natation depuis le site FFN Extranat (https://ffn.extranat.fr/webffn/).

## Prerequis

- Python 3.8 ou superieur
- Dependances : voir requirements.txt

## Installation

```
pip install -r requirements.txt
```

---


## Script get_data_deeper.py (donnees par type de competition)

Recupere par type : Championnats nationaux, Coupes regionales, International, etc.

### Commandes

- **python get_data_deeper.py**Traite tous les types par defaut (avec debug).
- **python get_data_deeper.py debug**Active les logs detailles.
- **python get_data_deeper.py fast**Pas de pause entre les requetes.
- **python get_data_deeper.py intl**Uniquement Competitions internationales (idtyp=7).
- **python get_data_deeper.py intl 7 8**Types 7 et 8 (international + interregional).
- **python get_data_deeper.py intl 1 2 3 fast debug**Types 1, 2, 3 en mode rapide avec debug.
- **python get_data_deeper.py intl list**Liste les competitions sans telecharger les resultats (fichier competitions_idtyp_7.json).
- **python get_data_deeper.py intl 15 10/01/2026 12/01/2026**
  Type 15 (Coupes Regionales) filtre par dates (du 10/01/2026 au 12/01/2026).

### Types (idtyp)

- 1 = Interclubs Avenirs (Reg. et Dep.)
- 2 = Interclubs Jeunes (Reg. et Dep.)
- 3 = Interclubs TC (Reg. et Dep.)
- 4 = Championnats Regionaux
- 5 = Meetings nationaux labellises
- 6 = Championnats nationaux
- 7 = Competitions internationales
- 8 = Competitions interregional
- 12 = Regionaux (web confrontation)
- 13 = Animation « A vos plots ! »
- 14 = Coupes Nationales
- 15 = Coupes Regionales

### Fichiers et dossiers generes

- Resultats par type : competitions_per_type/Nom du type/Nom competition.json
- Resume global : competitions_per_type/results_by_type.json
- Resumes : Resumes/resume.json et Resumes/resume_*.json
- Resumes par dates : competitions_per_dates/

---

## Exemples

```
pip install -r requirements.txt

python get_data_deeper.py intl fast

python get_data_deeper.py intl 15 01/01/2026 31/01/2026 debug
```

---

Le module get_data.py fournit l'extraction d'une page (classement, nageur, club, temps, splits, MPP).
get_data_deeper.py orchestre le scraping par type et genere les resumes (nombre de competitions, resultats, taux d'erreur).
