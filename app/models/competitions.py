from enum import Enum

class TypeCompetitionLabel(str, Enum):
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
