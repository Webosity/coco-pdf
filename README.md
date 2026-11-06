# Coco PDF

Lecteur et éditeur PDF pour Windows 10 et 11, pensé pour être simple à utiliser.

> Coco, c'est ma maman. À force de la voir galérer avec ses PDF, je lui ai créé un logiciel pour elle… et Coco PDF a vu le jour.

## Fonctions

- **Lire** : défilement continu, miniatures, zoom, recherche, impression.
- **Pages** : pivoter, supprimer, réordonner, fusionner, extraire, découper.
- **Modifier sur place** : cliquer sur un paragraphe pour le réécrire dans sa police d'origine, déplacer et redimensionner la zone ; déplacer, redimensionner et faire pivoter les images.
- **Ajouter** : du texte, des images, des **signatures** gardées dans une banque d'une session à l'autre.
- **Scans** : « Rendre le texte modifiable » décompose une page scannée en vrais éléments (texte, traits de tableau, aplats, logos) grâce à la reconnaissance de caractères.
- Formulaires, copie compressée, clic droit, annuler / rétablir.

## Installer

Télécharger `CocoPDF-Setup-<version>.exe` dans les [Releases](../../releases), puis le lancer (aucun droit administrateur requis).

## Construire depuis les sources

Prérequis : Python 3.13 et [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m coco_pdf
```

`build.ps1` produit `dist\CocoPDF\` (version portable) et `dist\CocoPDF-Setup-<version>.exe`.

## Licence

Coco PDF est un logiciel libre sous licence **GNU AGPL v3** : voir [LICENSE](LICENSE).
Copyright © 2026 SARL Digital Rhapsody, 31700 Blagnac, France.

Composants tiers :

| Composant | Licence |
|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) / MuPDF (rendu, édition, Tesseract intégré) | AGPL-3.0 |
| [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/) | LGPL-3.0 |
| [Modèle français Tesseract](https://github.com/tesseract-ocr/tessdata_best) (`assets/tessdata/fra.traineddata`) | Apache-2.0 |
