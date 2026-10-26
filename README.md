# heygen-tts

**Voix off gratuite, clonée, sans crédit vidéo.** Pilote le studio de voix HeyGen avec Playwright, intercepte le flux audio et écrit un MP3. Pas de capture d'écran, pas de perte de qualité, pas de crédit consommé.

> **English** — Free text-to-speech using HeyGen's voice studio preview. Cloned voices, no video credits, no screen recording. Works with any agent that can run a shell command.

---

## Pourquoi c'est gratuit

HeyGen facture les crédits au **rendu vidéo de l'avatar** — Avatar IV, 20 crédits par minute — pas à la synthèse vocale. L'aperçu audio du studio de voix est gratuit sur tous les plans.

Ce projet automatise cet aperçu : il saisit le texte, clique sur « Générer », récupère l'audio sur le réseau et le convertit en MP3. **Il ne clique jamais sur Generate ni Render Scene** dans l'éditeur vidéo.

## Ce que ça donne

| | |
|---|---|
| Coût | 0 crédit vidéo |
| Format | MP3 192 kbit/s, mono, 44,1 kHz |
| Voix | Bibliothèque HeyGen + tes clones |
| Testé | 643 caractères → 35,79 s, 860 Ko, -17,2 dB |

## Prérequis

- Python 3.9 ou plus
- Chrome installé — sinon Playwright télécharge Chromium
- `ffmpeg` et `ffprobe` dans le `PATH`

Playwright s'installe tout seul au premier lancement s'il manque.

## Installation

### Claude Code

```bash
git clone https://github.com/Taz-off/heygen-tts.git ~/.claude/skills/heygen-tts
```

### Codex, Gemini CLI, OpenCode et les autres

Ces agents lisent le dossier `~/.agents/skills/` :

```bash
git clone https://github.com/Taz-off/heygen-tts.git ~/.agents/skills/heygen-tts
```

Windows :

```powershell
git clone https://github.com/Taz-off/heygen-tts.git "$env:USERPROFILE\.agents\skills\heygen-tts"
```

### Cursor, Windsurf, Copilot

Pas de dossier de skills : ajoute ce bloc à ton `AGENTS.md` (ou `.cursor/rules`).

```markdown
## Voix off

Pour toute demande de voix off, narration ou TTS, lis `<chemin>/heygen-tts/SKILL.md`
puis lance :

python <chemin>/heygen-tts/scripts/heygen_tts.py tts --text-file <texte.txt> --out <sortie.mp3>
```

### Sans agent

```bash
python scripts/heygen_tts.py --help
```

## Première utilisation

```bash
python scripts/heygen_tts.py doctor
python scripts/heygen_tts.py login
python scripts/heygen_tts.py clone ma-voix.mp3
```

1. `doctor` vérifie Python, Playwright, le navigateur et ffmpeg.
2. `login` ouvre une fenêtre : connecte-toi à HeyGen à la main. Le profil persistant est conservé, tu ne le refais plus jamais.
3. `clone` envoie un échantillon (10 s minimum, MP3/WAV/MP4/WebM) et ouvre l'assistant HeyGen. Tu termines à la main : nom, consentement, entraînement. Une seule fois.

## Utilisation

| Commande | Effet |
|---|---|
| `doctor` | Vérifie l'environnement |
| `login` | Connexion unique, profil persistant |
| `voices` | Liste `mine` (clones) + `library` (bibliothèque) |
| `clone AUDIO` | Envoie un échantillon pour cloner |
| `clone AUDIO --dry-run` | Teste le wizard sans envoyer |
| `tts --text "..." --out a.mp3` | Texte → MP3 |
| `tts --text-file script.txt --out a.mp3` | Depuis un fichier |
| `tts ... --voice "Annie"` | Avec une voix précise |
| `tts ... --chunk` | Découpe en tranches de ~850 caractères |

Options : `--headed` (navigateur visible), `--debug` (screenshot + HTML), `--timeout 300`, `--url`, `--button`, `--chunk-chars`.

### Exemple

```bash
python scripts/heygen_tts.py tts --text-file script.txt --voice "Annie" --out narration.mp3
```

La recherche de voix est partielle : « Annie » trouve « Annie - Lifelike ». Si le nom n'existe pas, le script échoue avec la liste des voix au lieu de générer avec une voix par défaut.

## Sortie

La dernière ligne est du JSON :

```json
{"ok": true, "path": "narration.mp3", "duration": 35.79, "expected": 42.9, "bytes": 860203, "mean_db": -17.2, "silent": false, "chunks": 1, "voice": "Annie", "credits": 0}
```

| Champ | Sens |
|---|---|
| `ok` | Génération réussie |
| `silent` | `true` = fichier muet, ne pas livrer |
| `mean_db` | Volume moyen (seuil de silence : -45 dB) |
| `duration` / `expected` | Durée réelle vs estimée (15 caractères/s) |
| `credits` | Assertion de conception : aucun bouton facturé cliqué |

### Codes de sortie

| Code | Sens |
|---|---|
| 2 | Non connecté → lancer `login` |
| 3 | Vérification anti-bot non passée |
| 4 | Interface inattendue ou aucun audio |
| 5 | Erreur générique |

## Comment ça marche

Le studio n'expose pas de MP3 : il streame du **NDJSON** sur `api2.heygen.com/v2/online/creative_studio/text_to_speech.stream`. Chaque ligne contient un morceau MP3 en base64 (`audio_bytes`, `sequence_number`, `duration`) ; la dernière porte l'URL du fichier complet.

Le script recolle les morceaux dans l'ordre, ignore tout ce qui a été chargé **avant** le clic (les échantillons de la liste des voix) et rejette un audio trop court pour le texte demandé. C'est ce qui évite de livrer un bip de 2 secondes à la place de la narration.

Détails et procédures d'agent : [SKILL.md](SKILL.md).

## Limites et risques

- **CGU** — le téléchargement officiel est réservé aux plans payants ; ce projet récupère l'aperçu. Utilisation à tes risques.
- **Quota** — le bouton affiche « X min gratuites restantes ». Je ne sais pas s'il se consomme à la synthèse ou au rendu vidéo.
- **Interface mouvante** — les sélecteurs peuvent casser. `--debug` écrit screenshot + HTML dans `~/.config/heygen-tts/debug/`.
- **Plan gratuit** — aucun crédit HeyGen. Un compteur de crédits à l'écran signifie un compte payant.
- **Une génération à la fois** — le profil Chromium est verrouillé.
- **Clonage** — le script s'arrête après l'envoi de l'échantillon ; le reste se fait dans la fenêtre.

## Auto-test

```bash
python scripts/selftest.py
```

Monte un faux HeyGen local (page + audio réel) et vérifie l'interception réseau, la conversion MP3, la détection de silence et le découpage + concaténation, sans compte et sans réseau.

## Licence

MIT — voir [LICENSE](LICENSE).
