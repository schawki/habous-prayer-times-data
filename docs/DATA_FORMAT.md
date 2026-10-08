# Format des données / Data format

🇫🇷 Ce document décrit comment lire les fichiers JSON du dépôt (appli, script, intégration). 🇬🇧 How to read the repository's JSON files (app, script, integration).

> **Usage / Use.** Données non officielles reprises du site du Ministère des Habous et des Affaires islamiques ; le site fait foi. Usage personnel et non commercial tant qu'aucune autorisation des Habous n'a été obtenue. / Unofficial data taken from the Ministry's website, which remains authoritative. Personal, non-commercial use until the Ministry's permission is obtained.

## Où sont les fichiers / Where

Branche `main`, dossier `data/` :

| Fichier / File | Contenu / Content |
|---|---|
| `data/cities.json` | liste des 191 villes Habous / the 191 Habous cities |
| `data/times/<id>.json` | horaires d'une ville / one city's times |

Adresse brute / raw URL : `https://raw.githubusercontent.com/schawki/habous-prayer-times-data/main/data/…`. Ce service n'offre aucune garantie de disponibilité ni de débit : pour une appli publique, passez par un CDN ou votre propre copie, et mettez les données en cache. / No availability or rate guarantee: for a public app use a CDN or your own copy, and cache the data.

## `cities.json`

```json
{
 "updated": "2026-10-03T01:43:44+00:00",
 "cities": [
  { "id": 1, "name_ar": "الرباط", "name_fr": "Rabat", "lat": 34.0218, "lon": -6.8409, "verified": true },
  { "id": 30, "name_ar": "بوسكور" }
 ]
}
```

| Champ / Field | Sens / Meaning |
|---|---|
| `id` | identifiant Habous (paramètre `ville=` de leur site), 1–169 et 301–322. Stable. / Habous id (their `ville=` parameter). Stable. |
| `name_ar` | nom arabe du site Habous (toujours présent). / Arabic name from the Habous site (always present). |
| `name_fr` | nom français, **facultatif** (certaines villes n'en ont pas). / French name, **optional**. |
| `lat`, `lon` | degrés décimaux ; **facultatifs** : environ 19 villes n'ont pas encore de coordonnées. / decimal degrees; **optional**: some cities have none yet. |
| `verified` | `true` : les coordonnées ont été contrôlées avec l'heure du Dhuhr de la ville (écart de longitude < 0,8°). Absent = non contrôlées. / `true`: coordinates cross-checked against the city's own Dhuhr time. Absent = not checked. |

**Règles de lecture / Reading rules**

- Ignorez les villes sans `lat`/`lon` pour la recherche « ville la plus proche » ; elles restent utilisables si l'utilisateur les choisit dans une liste (par `name_fr` sinon `name_ar`). / Skip cities without `lat`/`lon` when looking for the nearest city; they can still be picked from a list.
- Ville la plus proche : distance à vol d'oiseau (haversine) entre la position et chaque ville géolocalisée. Définissez une distance maximale (l'intégration Home Assistant prend 30 km par défaut) au-delà de laquelle l'appli calcule les horaires plutôt que d'utiliser une ville lointaine (voyage à l'étranger, par exemple). / Nearest city: great-circle distance to every geolocated city. Set a maximum distance (the Home Assistant integration uses 30 km) beyond which the app calculates times instead.
- Les champs peuvent être ajoutés plus tard : ignorez ceux que vous ne connaissez pas. / New fields may appear: ignore unknown ones.

## `times/<id>.json`

```json
{
 "city_id": 58,
 "timezone": "Africa/Casablanca",
 "utc_offset": "+00:00",
 "offsets": { "2026-10-03": "+00:00" },
 "updated": "2026-10-03T01:43:44+00:00",
 "days": {
  "2026-10-03": { "fajr": "04:58", "sunrise": "06:23", "dhuhr": "12:25", "asr": "15:41", "maghrib": "18:17", "isha": "19:30" }
 }
}
```

| Champ / Field | Sens / Meaning |
|---|---|
| `city_id` | id de la ville (comme dans `cities.json`). |
| `timezone` | `Africa/Casablanca` (informatif). |
| `offsets` | décalage de l'heure légale marocaine **pour chaque jour** de `days` (clés `AAAA-MM-JJ`, valeurs `+00:00`). Prioritaire sur `utc_offset` : l'heure légale peut changer au milieu d'un fichier. Facultatif (absent des anciens fichiers). / offset of Moroccan legal time **for each day** of `days`. Takes priority over `utc_offset`, because legal time can change in the middle of a file. Optional (absent from older files). |
| `utc_offset` | décalage du **dernier jour** du fichier, au format `+00:00`. Repli quand `offsets` ne couvre pas un jour. Facultatif. / offset of the file's **last day**; fallback when `offsets` has no entry for a day. Optional. |
| `updated` | date UTC de la dernière collecte pour cette ville. / UTC time of the last collection. |
| `days` | clés `AAAA-MM-JJ` (date grégorienne) ; valeurs : `fajr`, `sunrise`, `dhuhr`, `asr`, `maghrib`, `isha`, au format `HH:MM` sur 24 h, **en heure légale marocaine**. |

**Règles de lecture / Reading rules**

- **Construisez l'instant** (date + heure) avec `offsets[jour]` s'il existe, sinon `utc_offset`, plutôt qu'avec le fuseau de l'appareil : cela évite les erreurs si la base de fuseaux du téléphone est ancienne (le Maroc change d'heure autour du Ramadan) et si l'utilisateur est à l'étranger. Sans décalage, utilisez `Africa/Casablanca`. / Build the instant from date + time + `offsets[day]` (else `utc_offset`) when present, not the device time zone.
- `sunrise` (Chourouk) n'est pas une prière : ne déclenchez pas d'adhan dessus. / `sunrise` is not a prayer.
- Un jour absent de `days` signifie « pas de données », pas « pas de prière » : prévoyez un repli (calcul local, dernier jour connu…). / A missing day means “no data”.
- Les heures sont à la minute, comme sur le site des Habous.

## D'où vient le décalage ? / Where does the offset come from?

🇫🇷 Il n'est **pas saisi à la main** : à chaque collecte, le script le **déduit des heures publiées**. Pour chaque jour, il compare le Dhuhr publié de chaque ville aux coordonnées vérifiées (au moins 20 villes) au midi solaire calculé à sa longitude ; l'écart est le décalage légal. Il retient la médiane, arrondie à 30 minutes, seulement si au moins 90 % des villes s'accordent à ±15 minutes et si la médiane est à moins de 10 minutes d'un multiple de 30. Sinon la collecte s'arrête en erreur et rien n'est publié (relancer à la main avec le champ `utc_offset` du workflow). Un changement d'heure légale du Maroc est ainsi pris en compte automatiquement, jour par jour. 🇬🇧 It is **not typed by hand**: at each collection the script **deduces it from the published times**. For each day it compares every verified city's published Dhuhr with the solar noon computed at its longitude (at least 20 cities); the gap is the legal offset. It keeps the median, rounded to 30 minutes, only if at least 90% of cities agree within ±15 minutes. Otherwise the run fails and nothing is published (run it by hand with the workflow's `utc_offset` field). A change of Moroccan legal time is therefore picked up automatically, day by day.

## Quelle période est couverte ? / What period is covered?

Le site des Habous ne publie que **le mois hijri en cours** (29 ou 30 jours). Chaque fichier contient donc ce mois, plus au plus 7 jours déjà passés. Les horaires du mois suivant n'existent qu'une fois que le site les affiche. / The Habous site only publishes the **current Hijri month**; each file holds that month plus up to 7 past days.

**Mise à jour / Updates** — un workflow GitHub passe chaque jour à 00:07 UTC. Il ne contacte le site que si les fichiers ne couvrent plus aujourd'hui, c'est-à-dire en pratique **une fois par mois hijri**, juste après minuit le premier jour du nouveau mois. / A GitHub workflow runs daily at 00:07 UTC and only contacts the site when files no longer cover today, i.e. about once per Hijri month.

**Fenêtre sans données / Window without data** — le premier jour du mois, le nouveau fichier n'est publié que quelques dizaines de minutes après minuit (la date du jour manque dans `days` d'ici là). L'appli doit alors calculer localement ou garder les dernières données, et revérifier ensuite. Si le site n'a pas changé de mois ou est en panne, la passe est retentée le lendemain. / On the first day of the month the new file appears some tens of minutes after midnight. The app should calculate locally or keep older data, then check again. If the site is late or down, the run is retried the next day.

## Bonnes pratiques de téléchargement / Good practice

- Téléchargez `cities.json` rarement (il change à peine) et les fichiers `times/<id>.json` **seulement pour les villes utilisées**, au plus une fois par jour, par exemple quand le jour courant manque dans votre cache. / Fetch `cities.json` rarely and only the cities you use, at most once a day.
- Gardez le dernier fichier valide en cache et ne le remplacez que par un JSON valide contenant `days`. / Keep the last valid file in cache.
- N'allez jamais chercher les données directement sur le site des Habous depuis une appli : c'est le rôle de ce dépôt, qui le fait avec parcimonie. / Do not scrape the Habous site from an app: that is this repository's job.
