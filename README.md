# Coco PDF

Lecteur et éditeur PDF pour Windows 10/11 (Python, PySide6, PyMuPDF).

## Fonctions

- **Lecture** : défilement continu, miniatures, zoom (Ctrl+molette), recherche (Ctrl+F, F3), aller à la page (Ctrl+G), impression, glisser-déposer d'un PDF, fichiers récents, PDF protégés par mot de passe.
- **Pages** : pivoter, supprimer, réordonner par glisser-déposer des miniatures, insérer une page blanche, insérer/fusionner d'autres PDF, extraire, découper.
- **Mode Modifier** (Ctrl+E) :
  - clic sur un paragraphe : il devient une zone de saisie posée sur la page, avec une barre flottante (police, taille, gras, italique, couleur, alignement). La poignée bleue en haut à gauche déplace la zone ; les poignées latérales et le coin la redimensionnent, et le texte se recompose. Ctrl+Entrée ou un clic ailleurs valide, Échap annule ;
  - clic sur une image : poignées pour la déplacer, la redimensionner (proportions gardées aux coins, Maj pour les libérer) et la faire pivoter à n'importe quel angle (Maj : crans de 15°), boutons ±90°, remise à 0° et suppression (Suppr).
- **Police d'origine conservée** : les polices intégrées aux PDF ne contiennent en général que les caractères déjà utilisés. Coco PDF retrouve donc la police complète installée sur Windows (`Calibri`, `Arial-BoldMT`, etc.) et ne garde à l'enregistrement que les caractères utilisés. Si la police n'est pas installée, la barre l'indique et une police standard proche est utilisée.
- **Ajouts** : texte libre (Ctrl+T), image (Ctrl+Maj+I), sélectionnée dès sa pose.
- **Signatures** : bouton « Signature » → banque d'images conservée sur le PC (`%LOCALAPPDATA%\Coco PDF\signatures`), par exemple « Signature simple », « Bon pour accord », « Lu et approuvé ». À l'import, le fond blanc d'une signature scannée ou photographiée devient transparent et l'image est recadrée. On choisit une signature, on clique sur la page, puis on l'ajuste avec les poignées.
- **Clic droit sur la page** : ajouter une zone de texte, une image ou une signature à cet endroit ; modifier le texte ou ajuster l'image sous le curseur ; couper, copier, coller ici, supprimer ; annuler, rétablir. Couper, copier et coller (Ctrl+X / C / V) marchent aussi sur l'image sélectionnée. Ce qui est copié dans Coco PDF garde son style ou sa taille ; une image ou un texte copiés depuis une autre application se collent aussi.
- **Formulaires** : remplissage des champs texte, cases, listes.
- **Compression** : « Enregistrer une copie compressée » (images rééchantillonnées à 150 dpi, flux compressés).
- **Rendre le texte modifiable (OCR)** : un bandeau s'affiche quand un document est scanné. Un clic décompose chaque page, sans aucune image de fond : les traits (tableaux, cadres) deviennent des traits vectoriels, les aplats (cellules grises, encadrés) des rectangles de couleur, et les logos, photos et tampons des images séparées que l'on peut déplacer. Le texte est lu par Tesseract (intégré à PyMuPDF ; seul `assets/tessdata/fra.traineddata` est livré) sur une copie de la page qui ne contient que lui, puis réécrit mot par mot en vrai texte avec sa taille, sa couleur, sa famille de police et le gras (détecté à partir de 200 dpi). Le résultat est enregistré à côté de l'original, sous le nom « nom (modifiable).pdf ». Le même outil, dans le menu Outils, répare les pages dont le texte s'affiche bien mais se lit comme du charabia. Limites : relire les noms et les chiffres ; l'italique et l'écriture manuscrite ne sont pas reconnus ; sur une feuille froissée, les zones déformées restent en image.
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
