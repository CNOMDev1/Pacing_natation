"""Énumération des types de compétition Extranat (libellés et ``idtyp``).

Ce module fait le lien entre les libellés affichés sur ffn.extranat.fr et
les identifiants numériques ``idtyp`` utilisés dans les URLs et le scraping
(``extranat_service``, routers, UI desktop).

Chaque membre de ``TypeCompetitionLabel`` expose la propriété ``idtyp`` pour
construire les URLs de collecte sans dupliquer la table de correspondance.
"""
from enum import Enum


class TypeCompetitionLabel(str, Enum):
    """Type de compétition FFN avec libellé UI et identifiant ``idtyp``.

    Hérite de ``str`` pour une sérialisation JSON directe du libellé.
    Les valeurs ``idtyp`` correspondent au ``<select id=liste_type>`` Extranat.

    Attributes:
        COMPETITIONS_INTERNATIONALES: idtyp=7
        CHAMPIONNATS_NATIONAUX: idtyp=6
        MEETINGS_NATIONAUX_LABELLISES: idtyp=5
        COUPES_NATIONALES: idtyp=14
        COMPETITIONS_INTERREGIONALES: idtyp=8
        REGIONAUX_WEB_CONFRONTATION: idtyp=12
        CHAMPIONNATS_REGIONAUX: idtyp=4
        COUPES_REGIONALES: idtyp=15
        INTERCLUBS_TC: idtyp=3
        INTERCLUBS_JEUNES: idtyp=2
        INTERCLUBS_AVENIRS: idtyp=1
        ANIMATION_A_VOS_PLOTS: idtyp=13
    """

    COMPETITIONS_INTERNATIONALES = "Compétitions internationales"
    CHAMPIONNATS_NATIONAUX = "Championnats nationaux"
    MEETINGS_NATIONAUX_LABELLISES = "Meetings nationaux labellisés"
    COUPES_NATIONALES = "Coupes Nationales"
    COMPETITIONS_INTERREGIONALES = "Compétitions interrégionales"
    REGIONAUX_WEB_CONFRONTATION = "Régionaux (web confrontation)"
    CHAMPIONNATS_REGIONAUX = "Championnats Régionaux"
    COUPES_REGIONALES = "Coupes Régionales"
    INTERCLUBS_TC = "Interclubs TC (Rég. & Dép.)"
    INTERCLUBS_JEUNES = "Interclubs Jeunes (Rég. & Dép.)"
    INTERCLUBS_AVENIRS = "Interclubs Avenirs (Rég. & Dép.)"
    ANIMATION_A_VOS_PLOTS = "Animation « A vos plots ! »"

    @property
    def idtyp(self) -> int:
        """Retourne l'identifiant numérique Extranat associé au libellé.

        Returns:
            int: Valeur ``idtyp`` pour les URLs ``competitions.php?idtyp=…``.
        """
        mapping = {
            TypeCompetitionLabel.COMPETITIONS_INTERNATIONALES: 7,
            TypeCompetitionLabel.CHAMPIONNATS_NATIONAUX: 6,
            TypeCompetitionLabel.MEETINGS_NATIONAUX_LABELLISES: 5,
            TypeCompetitionLabel.COUPES_NATIONALES: 14,
            TypeCompetitionLabel.COMPETITIONS_INTERREGIONALES: 8,
            TypeCompetitionLabel.REGIONAUX_WEB_CONFRONTATION: 12,
            TypeCompetitionLabel.CHAMPIONNATS_REGIONAUX: 4,
            TypeCompetitionLabel.COUPES_REGIONALES: 15,
            TypeCompetitionLabel.INTERCLUBS_TC: 3,
            TypeCompetitionLabel.INTERCLUBS_JEUNES: 2,
            TypeCompetitionLabel.INTERCLUBS_AVENIRS: 1,
            TypeCompetitionLabel.ANIMATION_A_VOS_PLOTS: 13,
        }
        return mapping[self]
