# 🎬 Cinema a Milano — pagina + aggiornamento automatico

Una pagina con la programmazione di **Cinema Beltrade**, **Anteo Palazzo del
Cinema** (Piazza XXV Aprile) e **Multisala Colosseo**: pill **V.O.** per i film
in lingua originale, orari di tutta la settimana, link 🎟 al biglietto di ogni
spettacolo Anteo, filtri per giorno e lingua.

## Le due versioni

- **Locale**: apri `index.html` (doppio click). Il Mac la aggiorna da solo
  (launchd, 08:10 e 17:40, o al primo risveglio).
- **Online** (GitHub Pages): stessa identica pagina, servita da GitHub, che si
  aggiorna da solo nel cloud — anche col Mac spento.

## Come funziona l'aggiornamento

```
siti dei cinema ──▶ update.py ──▶ cinema-data.js ──▶ index.html
                     ▲                │
        Mac (launchd 2×/giorno)      └─ bot GitHub Actions (3×/giorno)
                                          committa i dati → Pages ridistribuisce
```

Il pulsante **⟳** non può leggere i siti dei cinema (i browser bloccano le
richieste verso altri domini): rilegge solo l'ultimo `cinema-data.js` generato.
Chi genera i dati è lo script — in locale o nel cloud, a seconda della versione.

Aggiornamento immediato a mano: `python3 ~/cinema-milano/update.py`, poi ⟳.

## Pubblicare su GitHub Pages (una volta sola)

La cartella è già un repository git pronto, con il workflow che aggiorna i dati
nel cloud (`.github/workflows/update.yml`).

1. Su github.com: **New repository** → nome `cinema-milano` → **Public**
   (Pages gratuito richiede il repo pubblico; contiene solo orari del cinema) →
   **Create** senza README né .gitignore.
2. Sul Mac:
   ```sh
   cd ~/cinema-milano
   git remote add origin git@github.com:TUO-UTENTE/cinema-milano.git
   git push -u origin main
   ```
3. Nel repo su GitHub: **Settings → Pages → Source: *Deploy from a branch* →
   `main` / `(root)` → Save**.
4. Dopo ~1 minuto la pagina è su
   `https://TUO-UTENTE.github.io/cinema-milano/`
5. (Opzionale) per un aggiornamento immediato: tab **Actions → aggiorna-dati →
   Run workflow**. In poi parte da solo 3 volte al giorno
   (~08:10 · 17:10 · 21:10 ora italiana d'inverno, +1h d'estate; i cron di
   GitHub possono ritardare qualche minuto).

Una volta online, la pagina si tiene aggiornata da sola: il bot committa i
nuovi orari e il pulsante ⟳ (o il ritorno sulla scheda del browser) li carica.

### Nota sul repo locale

Il launchd del Mac continua ad aggiornare i file locali (la copia offline):
`cinema-data.js` e `index.html` risulteranno modificati nel repo locale. Se
un giorno fai `git pull` per prendere le modifiche del bot, prima rimetti
puliti i file generati:

```sh
git restore cinema-data.js index.html
```

…oppura disattiva l'aggiornamento locale (il cloud basta):

```sh
launchctl bootout gui/501 ~/Library/LaunchAgents/com.cinema-milano.update.plist
```

## File

| File | A cosa serve |
|---|---|
| `index.html` | la pagina (contiene anche una copia di riserva dei dati) |
| `cinema-data.js` | i dati, generati dallo script |
| `update.py` | legge i siti dei cinema e rigenera i dati (solo stdlib Python) |
| `.github/workflows/update.yml` | il bot GitHub Actions (aggiornamento nel cloud) |
| `update.log` | cronologia degli aggiornamenti locali (non committato) |
| `~/Library/LaunchAgents/com.cinema-milano.update.plist` | l'automazione locale (launchd) |

## Comandi utili

```sh
# aggiornamento manuale
python3 ~/cinema-milano/update.py

# seguire gli aggiornamenti automatici locali
tail -f ~/cinema-milano/update.log

# disattivare l'automazione locale
launchctl bootout gui/501 ~/Library/LaunchAgents/com.cinema-milano.update.plist

# riattivarla
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.cinema-milano.update.plist
```

## Fonti dei dati

- **Cinema Beltrade** → calendario iCal ufficiale (`beltrade.ics`) + scheda di
  ogni film per lingua/regia/cast.
- **Anteo Palazzo del Cinema** → API JSON del calendario spazioCinema
  (`@@get-calendario`, una chiamata per giorno): spettacoli del Palazzo con sala,
  lingua per singolo spettacolo, locandina e link biglietto. Le altre sedi
  (CityLife, Ariosto, Monza, Treviglio…) sono escluse di proposito.
- **Multisala Colosseo** → pagina programmazione (HTML strutturato), con versioni
  italiana e inglese; MyMovies conferma che le proiezioni in inglese sono
  sottotitolate in italiano.

Se un cinema è irraggiungibile, lo script riusa i dati dell'ultimo aggiornamento
riuscito e lo segnala nel log.

## Note

- Per includere anche CityLife/Ariosto nel circuito Anteo: in `update.py`,
  funzione `is_palazzo`, accetta anche i link `citylife.` / `ariosto.`.
- Panoramica di tutte le sale di Milano: <https://www.mymovies.it/cinema/milano/>
