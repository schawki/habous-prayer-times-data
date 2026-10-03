# Habous prayer times — data / Données des horaires Habous

**FR** — Ce dépôt contient les horaires de prière publiés par le Ministère des Habous et des Affaires islamiques (https://www.habous.gov.ma), mis en forme en fichiers JSON pour l'intégration Home Assistant [habous-prayer-times-ha](https://github.com/schawki/habous-prayer-times-ha).
**Ce dépôt n'est pas officiel et n'est pas affilié au Ministère.** Les horaires font foi sur le site des Habous ; en cas de doute, c'est lui qui prime. Usage personnel et non commercial.

**EN** — JSON files built from the prayer times published by the Moroccan Ministry of Habous and Islamic Affairs, for the Home Assistant integration above. **Unofficial, not affiliated with the Ministry.** The Ministry's website is authoritative. Personal, non-commercial use.

## Contenu

```
data/cities.json        villes (id Habous, noms FR/AR, latitude, longitude, verified)
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

Le workflow GitHub tourne **chaque jour à 00:07 UTC**, mais il ne fait presque toujours rien : avec `--skip-if-fresh`, le script regarde d'abord dans `data/` si les fichiers de toutes les villes couvrent encore aujourd'hui, et s'arrête alors **sans aucune requête** vers le site des Habous. Une passe complète (la liste des villes, puis les 191 horaires, environ 13 minutes) n'a lieu qu'**au changement de mois hijri**, quand la page des Habous affiche le nouveau mois. Les passages automatiques ne cherchent pas de coordonnées (`--no-geocode`). Le workflow reste lançable à la main (onglet Actions → « Mise à jour des données Habous » → Run workflow), avec une marge de 7 jours et la recherche de coordonnées.

### Fenêtre sans données au changement de mois

La page des Habous ne présente que le mois hijri en cours : les horaires du nouveau mois n'existent dans ce dépôt que quelques dizaines de minutes après minuit le premier jour du mois (passage de 00:07 UTC + environ 13 minutes de traitement). Pendant ce court intervalle, l'intégration Home Assistant n'a pas le fichier du jour : si son option « Calcul local si le fichier du dépôt est absent ou périmé » est cochée (par défaut), elle calcule localement les horaires. Si le site n'a pas encore changé de mois, ou s'il est inaccessible, la passe est retentée le lendemain ; si toutes les villes échouent, le workflow échoue et GitHub envoie un e-mail.

### Essai sur une ville (sur votre Mac)

```
python3 tools/build_data.py --data-dir /tmp/essai --city 58
cat /tmp/essai/times/58.json
```

### Coordonnées des villes

Le site des Habous ne donne que les noms (en arabe). Les coordonnées viennent, par ordre de priorité, de :
1. `tools/cities_curated.json` : villes corrigées à la main (noms français, et coordonnées quand la recherche automatique se trompe) ;
2. une recherche OpenStreetMap (Nominatim), qui ne retient que des lieux habités (pas de rues, de pays, de régions).

Chaque coordonnée est **contrôlée avec les horaires Habous eux-mêmes** (`tools/citycheck.py`) : l'heure du Dhuhr fixe la longitude d'une ville (4 minutes par degré). Si la longitude trouvée s'écarte de plus de 0,8° de celle que donne le Dhuhr, la coordonnée est écartée et le programme cherche une autre réponse. Le champ `verified: true` d'une ville de `cities.json` indique qu'elle a passé ce contrôle. Les villes qui n'ont aucune réponse acceptable sont listées à la fin de l'exécution : on les renseigne dans `cities_curated.json`.

### Certificat du site des Habous

Le serveur de habous.gov.ma n'envoie pas son certificat intermédiaire (Sectigo « Public Server Authentication CA DV R36 »). Un navigateur ou un Mac le retrouvent seuls, pas un serveur GitHub : sans lui, on obtient `CERTIFICATE_VERIFY_FAILED`. Il est donc fourni dans `certs/habous-intermediate.pem` (certificat public, valable jusqu'au 21 mars 2036) et passé avec `--ca-bundle`, qui l'**ajoute** aux certificats du système. La vérification des certificats reste active.

Pour le récupérer à nouveau (macOS/Linux) :

```
url=$(openssl s_client -connect www.habous.gov.ma:443 -servername www.habous.gov.ma </dev/null 2>/dev/null | openssl x509 -noout -text | grep "CA Issuers" | head -1 | sed 's/.*URI://')
curl -s "$url" -o inter.cer
openssl x509 -inform DER -in inter.cer -out certs/habous-intermediate.pem
```

## Licence et sources

Le code est sous licence MIT (voir `LICENSE`). Les horaires restent la propriété de leur éditeur (Ministère des Habous et des Affaires islamiques). Les coordonnées des villes proviennent d'OpenStreetMap (© contributeurs OpenStreetMap, ODbL) ou de `tools/cities_curated.json`.
