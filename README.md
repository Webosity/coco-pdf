# Coco PDF

Lecteur et éditeur PDF pour Windows 10/11 (Python, PySide6, PyMuPDF).

## Fonctions

- **Lecture** : défilement continu, miniatures, zoom (Ctrl+molette), recherche (Ctrl+F, F3), aller à la page (Ctrl+G), impression, glisser-déposer d'un PDF, fichiers récents, PDF protégés par mot de passe.
- **Pages** : pivoter, supprimer, réordonner par glisser-déposer des miniatures, insérer une page blanche, insérer/fusionner d'autres PDF, extraire, découper.
- **Texte existant** (Ctrl+E) : clic sur un texte → nouveau texte, taille, gras/italique, couleur. La police d'origine (souvent embarquée partiellement) est remplacée par la police standard la plus proche (Helvetica, Times, Courier).
- **Ajouts** : texte libre (Ctrl+T), image (Ctrl+I).
- **Formulaires** : remplissage des champs texte, cases, listes.
- **Compression** : « Enregistrer une copie compressée » (images rééchantillonnées à 150 dpi, flux compressés).
- **OCR** : ajoute une couche de texte invisible et cherchable. Nécessite Tesseract (`winget install UB-Mannheim.TesseractOCR`, avec la langue française).
- Annuler / rétablir (Ctrl+Z / Ctrl+Y) sur 30 niveaux.

## Développement

```powershell
py -3.13 -m venv $env:USERPROFILE\.venvs\coco-pdf
& $env:USERPROFILE\.venvs\coco-pdf\Scripts\python -m pip install -r requirements.txt
& $env:USERPROFILE\.venvs\coco-pdf\Scripts\python -m coco_pdf [fichier.pdf]
& $env:USERPROFILE\.venvs\coco-pdf\Scripts\python -m pytest -q
```

## Construire l'installeur

Prérequis : Inno Setup 6 (`winget install JRSoftware.InnoSetup`).

```powershell
.\build.ps1
```

Produit `dist\CocoPDF\` (version portable) et `dist\CocoPDF-Setup-<version>.exe`. L'installeur s'installe sans droits admin par défaut, crée le raccourci du menu Démarrer (Bureau en option) et inscrit Coco PDF dans « Ouvrir avec » pour les `.pdf`. Windows ne laisse pas un installeur s'imposer comme application par défaut : clic droit sur un PDF → Ouvrir avec → Choisir une autre application → Coco PDF → Toujours.

Pour une nouvelle version, changer le numéro dans `coco_pdf/__init__.py`, `installer.iss` et `version_info.txt`.

## Licence

PyMuPDF est sous AGPL : usage personnel/interne sans contrainte ; diffuser l'application à des tiers impose de publier son code source sous AGPL (ou d'acheter une licence commerciale Artifex).
