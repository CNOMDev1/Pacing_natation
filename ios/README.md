# PacingApp — prototype SwiftUI (iPad / macOS)

Application minimale pour illustrer la piste **§5.5** de la fiche mission : consultation terrain entraîneur, branchée sur l’API Python (ou données démo).

## Documentation

Voir [`docs/ios_mac_exploration_5_5.md`](../../docs/ios_mac_exploration_5_5.md).

## Ouvrir / lancer

```bash
open ios/PacingApp/PacingApp.xcodeproj
```

Destinations supportées : **My Mac**, **iPad Simulator**, iPhone (UI adaptée via NavigationSplitView).

Mode par défaut : **Démo** (JSON embarqué). Pour le mode Live :

```bash
uvicorn pacing.api.main:app --reload --host 0.0.0.0 --port 8000
```

Puis dans **Réglages** : mode Live, URL `http://127.0.0.1:8000` (Mac / Simulateur) ou IP LAN (iPad physique).

## Build CLI

```bash
xcodebuild -project ios/PacingApp/PacingApp.xcodeproj -scheme PacingApp -destination 'platform=macOS' build
```
