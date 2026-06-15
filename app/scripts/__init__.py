"""Scripts exécutables de vérification, maintenance et prétraitement des données.

Ce package regroupe les pipelines offline qui transforment les données brutes
(``data/raw/``) en JSON normalisés (``data/processed/``) ou renouvellent les
tokens d'accès API :

- ``extranat_preprocessing`` — nettoyage des JSON Extranat scrapés
- ``usaswimming_preprocessing`` — nettoyage et regroupement USA Swimming
- ``frmnatation_preprocessing`` — filtrage et normalisation FRM Natation
- ``get_token_usaswimming`` — capture du Bearer token Data Hub via Playwright
"""
