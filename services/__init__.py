"""Secrets et état local du poste (hors code métier).

Ce paquet ne contient plus de code : ``api_core`` et ``app_service`` ont été
déplacés dans ``pacing.application``. Il ne subsiste que des fichiers locaux,
non versionnés, que ``pacing.config.paths.SECRETS_DIR`` continue de pointer :
``bearer_token.txt`` (jeton USA Swimming) et ``state.json`` (session Playwright).
"""
