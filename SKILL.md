---
name: heygen-tts
description: Use when the user asks for a voiceover, narration, text-to-speech, "lis ce texte", "fais-moi une voix off", dubbing a script, or wants a cloned voice without paying per character. Also use when ElevenLabs credits are exhausted, when a text must be read aloud in a specific voice, or when the user asks for "ElevenLabs gratuit". Drives the HeyGen voice studio in the background and never spends video credits.
---

# HeyGen TTS — voix clonée, 0 crédit

## Principe

HeyGen facture les crédits au **rendu vidéo de l'avatar** (Avatar IV : 20 crédits/minute), pas à la synthèse vocale. L'aperçu audio est gratuit sur tous les plans. Ce skill pilote le studio de voix, récupère le fichier audio directement sur le réseau, et **ne clique jamais** sur Generate ni Render Scene.

Résultat : un MP3 propre, sans capture d'écran, sans perte de qualité, sans crédit consommé.

## Comment l'audio est récupéré (vérifié le 26/10/2026)

Le studio n'expose pas un MP3 à télécharger : il **streame du NDJSON** sur `api2.heygen.com/v2/online/creative_studio/text_to_speech.stream`. Chaque ligne contient un morceau MP3 en base64 (`audio_bytes`, `sequence_number`, `duration`) et la dernière porte l'URL du fichier complet. Le script lit ce flux, recolle les morceaux dans l'ordre et vérifie la durée.

Il ignore en plus tout ce qui a été chargé **avant** le clic (les échantillons de la liste des voix) et rejette un audio trop court pour le texte demandé (`expected` = longueur / 15 s, seuil à 40 %). C'est ce qui évite de livrer un bip de 2 secondes à la place de la narration.

## Périmètre

**Fait :** connexion unique, changement de voix (bibliothèque HeyGen), envoi d'un échantillon pour cloner, génération de texte en MP3, découpage automatique, vérification qualité.

**Ne fait pas :** créer le compte HeyGen, terminer le clonage à la place de l'utilisateur (nom, consentement et entraînement se font dans la fenêtre), contourner un paywall ou un captcha, appeler l'API HeyGen (payante), utiliser un moteur TTS local.

## Première installation — checklist

1. `python scripts/heygen_tts.py doctor` → doit afficher `playwright: true` et un numéro de navigateur. Si Playwright manque, le script l'installe lui-même ; ne pas le faire à la main.
2. `python scripts/heygen_tts.py login` → navigateur visible, l'utilisateur se connecte. Le profil persistant est conservé, plus jamais de login ensuite.
3. `python scripts/heygen_tts.py clone echantillon.mp3` → ouvre la fenêtre, choisit « Téléverser de l'audio » et envoie l'échantillon (10 s minimum, MP3/WAV/MP4/WebM). **L'utilisateur termine dans la fenêtre** : nom, consentement, entraînement. Le clone apparaît ensuite dans « Mes voix » et **n'est jamais à refaire**. Vérifier avec `voices` → `mine`.
4. `python scripts/heygen_tts.py tts --text "bonjour" --out test.mp3 --debug` → premier essai réel. Le `--debug` est recommandé : il écrit screenshot + HTML dans `debug/` si l'interface change.

## Commandes

| Commande | Effet |
|---|---|
| `doctor` | Vérifie Python, Playwright, navigateur, ffmpeg |
| `login` | Connexion unique, profil persistant |
| `voices` | Liste `mine` (voix clonées) + `library` (bibliothèque HeyGen) |
| `clone AUDIO` | Envoie un échantillon ; nom + consentement dans la fenêtre |
| `clone AUDIO --dry-run` | Vérifie le wizard sans envoyer le fichier |
| `tts --text "..." --voice NOM --out audio.mp3` | Texte → MP3 avec la voix choisie |
| `tts --text-file script.txt --out audio.mp3` | Idem depuis un fichier |
| `tts ... --chunk` | Découpe en tranches de ~850 caractères et concatène |

Options : `--headed` (navigateur visible), `--debug` (HTML + screenshot), `--timeout 300`, `--url` / `--button` (si l'interface change), `--chunk-chars 850`, `--limit 40` (voices), `--wait 900` (clone).

## Changer de voix (vérifié le 27/10/2026)

`voices` renvoie deux listes : `mine` (les voix clonées) et `library` (les 29 voix HeyGen visibles). Pour en utiliser une :

```
tts --text-file script.txt --voice "Annie" --out audio.mp3
```

La recherche est partielle : « Annie » trouve « Annie - Lifelike ». Le script ouvre le sélecteur du studio, cherche dans la bibliothèque, clique la ligne et **vérifie la voix active** dans la barre du studio. Si le nom n'existe pas, il échoue avec les premiers résultats au lieu de générer avec la voix par défaut.

Pour ta propre voix : `clone echantillon.mp3`, puis `--voice "Nom du clone"` comme n'importe quelle autre voix.

## Procédure quotidienne

1. Vérifier que le texte existe et n'est pas vide. Préférer `--text-file` pour éviter les problèmes de quoting.
2. Lancer `tts` en **arrière-plan** (`background=true`) : une génération prend de 30 s à plusieurs minutes.
3. Lire la dernière ligne de sortie : JSON `{"ok": true, "path": ..., "duration": ..., "mean_db": ...}`.
4. Vérifier **avant de livrer** :
   - `ok` vaut `true`
   - `silent` vaut `false` (sinon le fichier est muet, ne pas le livrer)
   - `duration` cohérente avec le texte (~15 caractères par seconde)
   - `bytes` > 20 000
5. Rendre le chemin, la durée et `credits: 0`. Rien d'autre.

## Garde-fous — non négociables

- **Ne jamais générer de vidéo** : dans l'éditeur vidéo, « Generate » / « Render Scene » facture 20 crédits/minute. Le bouton « Générer » du **studio de voix** produit l'aperçu audio gratuit — c'est le seul que le script clique.
- **Ne jamais cliquer « Render Scene »** sauf demande explicite de l'utilisateur.
- **Ne jamais enregistrer le projet** dans le compte HeyGen.
- **Ne jamais tenter de contourner un paywall, un captcha ou un blocage de compte.** Si un mur apparaît : arrêt, signalement.
- Une seule génération à la fois : le profil Chromium est verrouillé.

## Anti-bot

En headless, si une vérification apparaît, le script relance automatiquement le navigateur en **visible** et attend que l'utilisateur coche la case (5 minutes max). C'est le comportement voulu : invisible quand ça passe, visible quand il faut un humain. Ne pas court-circuiter cette attente.

## Échecs

| Symptôme | Réaction |
|---|---|
| `non connecte` (code 2) | Lancer `login` |
| `verification anti-bot non passee` (code 3) | Relancer en `--headed`, laisser l'utilisateur cocher |
| `interface inattendue` (code 4) | Relancer avec `--debug`, montrer le screenshot et le HTML à l'utilisateur |
| `aucun audio capture` (code 4) | Idem ; essayer `--url` avec l'éditeur AI Studio |
| `silent: true` | Ne pas livrer ; relancer avec `--headed --debug` |
| `audio trop court` | Le script a attrapé un échantillon ; relancer, ou `--chunk` si le texte est très long |
| Aperçu limité à 1 minute | Relancer avec `--chunk` |
| Voix introuvable | `voices` pour voir les noms exacts ; la recherche est partielle (« Annie » suffit) |
| `wizard de clonage inattendu` | `clone ... --dry-run` pour isoler, puis `--debug` ; l'interface a changé |
| Le clone n'apparaît pas dans `mine` | L'entraînement n'est pas fini, ou le consentement n'a pas été validé dans la fenêtre |

## Vérification du skill lui-même

`python scripts/selftest.py` monte un faux HeyGen local et prouve l'interception réseau, la conversion MP3, la détection de silence et le découpage + concaténation. À relancer après toute modification du script.

## Vérifié en conditions réelles (26/10/2026)

- Studio `creative_studio/voice`, texte de 643 caractères → **35,79 s, 860 Ko, -17,2 dB, `silent: false`**, durée identique à celle annoncée par le flux.
- Changement de voix : `--voice "Annie"` → « Little Annie » appliquée, 129 caractères → **6,82 s, 165 Ko, -17,7 dB**.
- `voices` → 29 voix dans `library`, `mine` vide (aucun clone sur ce compte).
- `clone ... --dry-run` → wizard atteint, champ d'upload détecté (MP3/WAV/MP4/WebM).
- Le champ de saisie est un `contenteditable`, pas un `textarea`.
- La voix par défaut s'appelle « DARAN INSIDE 2 with mic ».

## Limites connues

- L'interface HeyGen peut changer : en cas d'échec, relancer avec `--debug` et regarder `debug/`.
- Le clonage s'arrête après l'envoi de l'échantillon : nom, consentement et entraînement ne sont pas automatisés ni vérifiés au-delà de l'upload.
- L'interface utilise des apostrophes typographiques (« Téléverser de l’audio ») : les sélecteurs doivent passer par une regex, jamais par une chaîne littérale.
- Le modal du studio et la page `/avatar/voices` n'utilisent pas le même composant de liste (`voice-row` vs `voice-card-play-btn`) ; `voices` et `pick_voice` gèrent les deux.
- La durée maximale d'un aperçu gratuit n'est pas connue. Un texte de 643 caractères passe (35,8 s) ; au-delà, utiliser `--chunk`.
- Le bouton affichait « 8 min gratuites restantes » : un quota existe. Je ne sais pas s'il se consomme à la synthèse ou au rendu vidéo — à surveiller.
- Le téléchargement officiel est réservé aux plans payants ; ce skill récupère l'aperçu. Risque CGU / fermeture de compte à signaler une fois, sans moraliser.
- Le plan gratuit HeyGen n'a **aucun crédit** : un compteur de crédits à l'écran signifie un compte payant.
- `credits: 0` est une affirmation de conception (aucun bouton facturé cliqué), pas une lecture du solde du compte.
