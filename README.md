# Habous prayer times — data / Données des horaires Habous

**FR** — Ce dépôt contient les horaires de prière publiés par le Ministère des Habous et des Affaires islamiques (https://www.habous.gov.ma), mis en forme en fichiers JSON pour l'intégration Home Assistant [habous-prayer-times-ha](https://github.com/schawki/habous-prayer-times-ha).
**Ce dépôt n'est pas officiel et n'est pas affilié au Ministère.** Les horaires font foi sur le site des Habous ; en cas de doute, c'est lui qui prime. Usage personnel et non commercial.

**EN** — JSON files built from the prayer times published by the Moroccan Ministry of Habous and Islamic Affairs, for the Home Assistant integration above. **Unofficial, not affiliated with the Ministry.** The Ministry's website is authoritative. Personal, non-commercial use.

## Contenu

```
data/cities.json        villes (id Habous, noms FR/AR, latitude, longitude)
data/times/<id>.json    horaires d'une ville
```

Exemple de `times/<id>.json` :

```json
{
 "city_id": 58,
 "timezone": "Africa/Casablanca",
 "utc_offset": "+00:00",
 "updated": "2026-10-02T09:00:00+00:00",
 "days": { "2026-10-02": { "fajr": "05:10", "sunrise": "06:30", "dhuhr": "13:00", "asr": "16:20", "maghrib": "18:50", "isha": "20:10" } }
}
```

Les heures sont les heures légales marocaines du jour concerné. `utc_offset` est facultatif (écrit seulement si on le fournit au constructeur).

## Comment les données sont produites

`tools/build_data.py` lit la page des Habous **avec parcimonie** : une requête par ville seulement quand ses données expirent bientôt (environ une fois par mois hijri), avec une pause de 2 s entre deux requêtes, un User-Agent qui s'identifie, et jamais de contournement de la vérification des certificats. Si la page n'a pas la structure attendue, **rien n'est écrit** : les anciennes données restent en place plutôt que de publier des horaires faux.

Le workflow GitHub est **manuel** (onglet Actions → « Mise à jour des données Habous » → Run workflow). Le déclenchement automatique est prêt mais commenté dans `.github/workflows/update-data.yml`.

### Essai sur une ville (sur votre Mac)

```
python3 tools/build_data.py --data-dir /tmp/essai --city 58
cat /tmp/essai/times/58.json
```

Si l'erreur concerne le certificat du site, fournissez la chaîne complète : `--ca-bundle chemin/vers/chaine.pem`.

## Licence et sources

Le code est sous licence MIT (voir `LICENSE`). Les horaires restent la propriété de leur éditeur (Ministère des Habous et des Affaires islamiques). Les coordonnées des villes proviennent d'OpenStreetMap (© contributeurs OpenStreetMap, ODbL).
