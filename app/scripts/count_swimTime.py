import json
from collections.abc import Mapping, Sequence

def iter_swim_time_seconds(obj):
    """
    Générateur qui parcourt récursivement un objet JSON
    (dicts, listes, etc.) et renvoie toutes les valeurs
    trouvées pour la clé 'SwimTimeSeconds'.
    """
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k == "SwimTimeSeconds":
                yield v
            # continuer à descendre récursivement
            yield from iter_swim_time_seconds(v)
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes)):
        for item in obj:
            yield from iter_swim_time_seconds(item)

def compter_swim_time_seconds(path_json):
    with open(path_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    nb_zero = 0
    nb_non_zero = 0

    for val in iter_swim_time_seconds(data):
        # on ignore les valeurs non numériques
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue

        if v == 0:
            nb_zero += 1
        else:
            nb_non_zero += 1

    return nb_zero, nb_non_zero

if __name__ == "__main__":
    # Remplace ce chemin par ton fichier, par ex. :
    # "app/data/cleaned_data/extranat/competitions_per_type/..."
    chemin_fichier = "Phase finale Coupe de France des Départements-Messieurs.json"

    zero, non_zero = compter_swim_time_seconds(chemin_fichier)
    print(f"Nombre de SwimTimeSeconds == 0 : {zero}")
    print(f"Nombre de SwimTimeSeconds != 0 : {non_zero}")