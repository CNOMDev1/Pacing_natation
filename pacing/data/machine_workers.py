"""Détection du profil machine et recommandation du nombre de workers.

Ce module inspecte la RAM et le CPU de la machine hôte, la classe en trois
profils (modeste, standard, haute performance), puis propose un nombre de
threads adapté au type de tâche parallèle.

Le flux de décision :
1. **Détection matérielle** — ``detect_machine_info()`` lit la RAM physique
   (sysctl sur macOS, ``/proc/meminfo`` sur Linux, WinAPI sur Windows) et le
   nombre de cœurs logiques.
2. **Classification** — ``classify_machine_profile()`` dérive le profil à partir
   de la RAM (prioritaire) ou du CPU en secours si la RAM est indétectable.
3. **Plafonds** — deux budgets distincts selon le type de tâche :
   ``memory_heavy`` (ex. cache Parquet annuel) et ``io_bound`` (lectures disque
   ou réseau).
4. **Recommandation finale** — le minimum entre le plafond profil, le plafond
   RAM et le nombre de cœurs CPU.

Points d'entrée publics : ``recommended_cache_build_workers()`` et
``recommended_io_workers()``.
"""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

# --- Seuils de classification (Go de RAM physique) ---

_RAM_MODEST_MAX_GB = 12.0  # < 12 Go → profil modeste
_RAM_STANDARD_MAX_GB = 28.0  # 12–28 Go → standard ; ≥ 28 Go → haute performance

# --- Budget mémoire pour les tâches « une grosse année en RAM » ---

_RAM_RESERVE_GB = 4.0  # mémoire laissée au système et aux autres processus
_RAM_PER_MEMORY_WORKER_GB = 2.0  # estimation par worker (JSON annuel en mémoire)

# Plafonds par profil pour les tâches gourmandes en RAM (ex. cache Parquet annuel)
_PROFILE_MEMORY_WORKER_CAP = {
    "modeste": 2,
    "standard": 4,
    "haute_performance": 8,
}

# Plafonds par profil pour les tâches I/O (lectures disque / réseau)
_PROFILE_IO_WORKER_CAP = {
    "modeste": 4,
    "standard": 8,
    "haute_performance": 16,
}

# Types de tâches supportés par ``recommended_workers``
TaskKind = Literal["memory_heavy", "io_bound"]


class MachineProfile(str, Enum):
    """Profil de performance déduit des ressources matérielles.

    Attributes:
        MODEST: Machine limitée en RAM (< 12 Go) ou peu de cœurs.
        STANDARD: Configuration intermédiaire (12–28 Go).
        HIGH_PERFORMANCE: Machine confortable (≥ 28 Go).
    """

    MODEST = "modeste"
    STANDARD = "standard"
    HIGH_PERFORMANCE = "haute_performance"


@dataclass(frozen=True)
class MachineInfo:
    """Instantané des ressources détectées sur la machine hôte.

    Attributes:
        ram_bytes (Optional[int]): RAM physique totale en octets, ou ``None``.
        ram_gb (Optional[float]): RAM en gigaoctets (arrondi), ou ``None``.
        cpu_count (int): Nombre de cœurs logiques disponibles.
        profile (MachineProfile): Profil dérivé de la RAM et du CPU.
    """

    ram_bytes: Optional[int]
    ram_gb: Optional[float]
    cpu_count: int
    profile: MachineProfile


def system_ram_bytes() -> Optional[int]:
    """Détecte la RAM physique totale sans dépendance externe.

    Utilise ``sysctl`` sur macOS, ``/proc/meminfo`` sur Linux et l'API
    ``GlobalMemoryStatusEx`` sur Windows.

    Returns:
        Optional[int]: Taille en octets, ou ``None`` si la plateforme est inconnue
            ou si la lecture échoue.

    Raises:
        Aucune exception propagée ; les erreurs sont interceptées et renvoient ``None``.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            # hw.memsize retourne la RAM physique totale en octets
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return int(result.stdout.strip())
        if system == "Linux":
            # MemTotal est exprimé en kioctets dans /proc/meminfo
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        if system == "Windows":
            import ctypes

            # Structure WinAPI pour GlobalMemoryStatusEx
            class _MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
    except (OSError, ValueError, subprocess.SubprocessError, FileNotFoundError):
        return None
    return None


def classify_machine_profile(
    ram_gb: Optional[float],
    cpu_count: int,
) -> MachineProfile:
    """Classe la machine selon la RAM (prioritaire) ou le CPU en secours.

    La RAM est le critère principal car elle conditionne directement le
    parallélisme des tâches ``memory_heavy``. Si la RAM est indétectable,
    on estime le profil à partir du nombre de cœurs.

    Args:
        ram_gb (Optional[float]): RAM totale en Go, ou ``None`` si indétectable.
        cpu_count (int): Nombre de cœurs logiques.

    Returns:
        MachineProfile: Profil modeste, standard ou haute performance.
    """
    if ram_gb is not None:
        if ram_gb < _RAM_MODEST_MAX_GB:
            return MachineProfile.MODEST
        if ram_gb < _RAM_STANDARD_MAX_GB:
            return MachineProfile.STANDARD
        return MachineProfile.HIGH_PERFORMANCE

    # RAM inconnue : repli conservateur sur le nombre de cœurs
    if cpu_count <= 4:
        return MachineProfile.MODEST
    if cpu_count <= 8:
        return MachineProfile.STANDARD
    return MachineProfile.HIGH_PERFORMANCE


def detect_machine_info() -> MachineInfo:
    """Inspecte la machine et retourne RAM, CPU et profil.

    Agrège ``system_ram_bytes()``, ``os.cpu_count()`` et
    ``classify_machine_profile()`` en un instantané unique.

    Returns:
        MachineInfo: Ressources détectées et profil associé.
    """
    ram_bytes = system_ram_bytes()
    ram_gb = round(ram_bytes / (1024 ** 3), 1) if ram_bytes is not None else None
    cpu_count = os.cpu_count() or 1
    profile = classify_machine_profile(ram_gb=ram_gb, cpu_count=cpu_count)
    return MachineInfo(
        ram_bytes=ram_bytes,
        ram_gb=ram_gb,
        cpu_count=cpu_count,
        profile=profile,
    )


def _workers_cap_for_profile(profile: MachineProfile, task: TaskKind) -> int:
    """Retourne le plafond de workers associé au profil et au type de tâche.

    Args:
        profile (MachineProfile): Profil machine détecté.
        task (TaskKind): ``memory_heavy`` ou ``io_bound``.

    Returns:
        int: Nombre maximal de workers recommandé pour ce profil.
    """
    caps = _PROFILE_MEMORY_WORKER_CAP if task == "memory_heavy" else _PROFILE_IO_WORKER_CAP
    return caps[profile.value]


def _workers_cap_from_ram(ram_gb: float, task: TaskKind) -> int:
    """Calcule un plafond RAM pour éviter de charger trop de données en parallèle.

    Pour ``memory_heavy``, soustrait une réserve système puis divise par le
    budget estimé par worker. Pour ``io_bound``, autorise environ un worker
    par 2 Go de RAM (moins contraignant car peu de données en mémoire).

    Args:
        ram_gb (float): RAM totale en Go.
        task (TaskKind): Type de tâche ; seul ``memory_heavy`` applique un budget strict.

    Returns:
        int: Nombre maximal de workers selon la mémoire disponible (≥ 1).
    """
    if task != "memory_heavy":
        # Tâches I/O : heuristique plus permissive (1 worker / 2 Go)
        return max(1, int(ram_gb // 2))

    # Tâches mémoire : (RAM - réserve) / budget par worker
    return max(
        1,
        int((ram_gb - _RAM_RESERVE_GB) // _RAM_PER_MEMORY_WORKER_GB),
    )


def recommended_workers(task: TaskKind = "io_bound") -> int:
    """Recommande un nombre de workers selon la machine et le type de tâche.

    Combine trois contraintes : plafond du profil machine, plafond RAM et
    nombre de cœurs CPU. Le résultat est toujours ≥ 1 et ≤ ``cpu_count``.

    Args:
        task (TaskKind): ``memory_heavy`` pour des tâches chargeant de gros
            volumes en RAM (ex. conversion JSON annuel → Parquet).
            ``io_bound`` pour lectures disque ou réseau parallèles.

    Returns:
        int: Nombre de threads recommandé.
    """
    info = detect_machine_info()
    profile_cap = _workers_cap_for_profile(info.profile, task)

    if info.ram_gb is not None:
        ram_cap = _workers_cap_from_ram(info.ram_gb, task)
        # Le plafond effectif est le plus restrictif entre profil et RAM
        effective_cap = min(profile_cap, ram_cap)
    else:
        effective_cap = profile_cap

    # Ne jamais dépasser le nombre de cœurs logiques
    return max(1, min(info.cpu_count, effective_cap))


def recommended_cache_build_workers() -> int:
    """Workers pour la construction du cache Parquet USA Swimming.

    Chaque worker peut charger une année entière de JSON en mémoire ; le plafond
    reste volontairement bas sur les machines modestes pour éviter les OOM.

    Returns:
        int: Nombre de threads recommandé pour ``build_parquet_cache``.
    """
    return recommended_workers(task="memory_heavy")


def recommended_io_workers() -> int:
    """Workers pour des tâches parallèles dominées par l'I/O.

    Convient aux lectures disque, téléchargements réseau ou parsing de fichiers
    où la mémoire par worker reste faible.

    Returns:
        int: Nombre de threads recommandé pour lectures disque ou réseau.
    """
    return recommended_workers(task="io_bound")


def _format_profile_report(info: MachineInfo) -> str:
    """Formate un résumé lisible du profil machine.

    Args:
        info (MachineInfo): Informations détectées.

    Returns:
        str: Texte multi-lignes pour affichage terminal.
    """
    ram_label = f"{info.ram_gb} Go" if info.ram_gb is not None else "inconnue"
    lines = [
        f"RAM totale    : {ram_label}",
        f"CPU (cœurs)   : {info.cpu_count}",
        f"Profil        : {info.profile.value}",
        f"Workers cache : {recommended_cache_build_workers()}",
        f"Workers I/O   : {recommended_io_workers()}",
    ]
    return "\n".join(lines)


def main() -> int:
    """Point d'entrée CLI : affiche le profil machine et les recommandations.

    Usage : ``python -m services.machine_workers``.

    Returns:
        int: Code de sortie (0).
    """
    info = detect_machine_info()
    print(_format_profile_report(info))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
