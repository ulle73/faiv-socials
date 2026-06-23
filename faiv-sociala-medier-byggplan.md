# FAIV Sociala Medier — Byggplan (budgetoptimerad)

## Kostnadsmål

| Komponent | Kostnad/månad |
|---|---|
| Apify Free | $0 |
| OpenRouter | ~$1–3 |
| GitHub Actions | $0 |
| Google Drive/Sheets | $0 |
| **Totalt** | **~$1–3/månad** |

---

## Hur vi ryms i Apify Free ($5/månad)

87 konton, men vi kör **inte dagligen**. Istället:

- Dela 87 konton i 3 batchar (~29 konton var)
- Kör en batch varannan dag = varje konto bevakas var 6:e dag
- 29 konton × 12 poster × ~15 körningar/månad = **~5 200 poster/månad**
- HTTP-only scraper: $0,30/1 000 = **~$1,56 i usage**
- Proxy ingår i Apify Free (datacenter), residential behövs inte om vi kör HTTP-only utan cookies
- Kvar för felsökning och omkörningar: ~$3,44

Det ryms. Men om $5 tar slut pausas körningar till nästa månad — inget overage, inget att betala.

---

## OpenRouter istället för OpenAI

OpenRouter ger tillgång till hundratals modeller via ett enda API. Du byter modell genom att ändra en rad i Google Sheet — ingen kodändring.

Rekommenderade modeller för detta system:

**Analys och scoring** — `google/gemini-flash-1.5` (~$0,075/1M tokens, extremt billig, bra på strukturerad analys)

**FAIV-omskrivning** — `anthropic/claude-haiku-3.5` eller `mistralai/mistral-small` (~$0,20–0,80/1M tokens, bra svenska)

**Fallback** — `meta-llama/llama-3.1-8b-instruct` (nästan gratis, används om budget tar slut)

Vid 5 förslag per körning, 3 prompts per förslag, ~800 tokens per prompt = ~12 000 tokens/körning × 15 körningar = **~180 000 tokens/månad = under $1** med Gemini Flash.

Modellval styrs från en cell i Google Sheet — `Settings`-flik med `analysis_model` och `proposal_model`. Systemet läser värdena vid varje körning.

---

## Förenklingar jämfört med ursprungsplan

Eftersom vi optimerar hårt på kostnad och enkelhet tas några komponenter bort eller förenklas:

**Borttaget:**
- Session check-jobb (extra Actions-körning, onödig komplexitet)
- Residential proxies (kostar extra, HTTP-only räcker för offentliga profiler)
- Separat Instagram-bevakningskonto (behövs inte med HTTP-only utan login)
- SQLite / persistent disk (Google Sheet är state)

**Förenklat:**
- Scoring sker i ett enda OpenRouter-anrop istället för kedja av prompts
- Bildmatchning matchar enbart på mappnivå, inte enskilda filer (sparar tokens)
- Google Doc genereras bara om det finns minst 3 godkända kandidater — annars bara e-post med varning

---

## Google Sheet som kontrollpanel

Sex flikar plus en Settings-flik:

**Settings** — här styr du systemet utan kod:

| Inställning | Standardvärde | Beskrivning |
|---|---|---|
| analysis_model | google/gemini-flash-1.5 | Modell för scoring |
| proposal_model | anthropic/claude-haiku-3.5 | Modell för omskrivning |
| min_score | 60 | Kandidattröskel |
| posts_per_account | 12 | Max poster per konto |
| notify_email | din@epost.se | Felnotiser |
| active_batch | A | Vilken batch körs idag (roteras automatiskt) |

Ändra `proposal_model` till `mistralai/mistral-small` om du vill spara pengar en månad. Ändra tillbaka om kvaliteten sjunker. Ingen kod att röra.

**Sources** — importerad från din Excel. Kolumner: handle, prioritet, land, kategori-fit, aktiv, batch (A/B/C), senast hämtad, status (ok / blockerad / tom). För att pausa ett konto ändrar du aktiv till nej.

**Collected Posts** — rådata från Apify. En rad per post: källa, URL, publiceringstid, caption, media-URL, hook-signal, batch-datum.

**Candidates** — poster som passerat scoring. Alla fält från Collected Posts plus FAIV-fit-poäng, lead-potential, hook-styrka, visuell överförbarhet, novelty, totalpoäng.

**Approved Proposals** — färdiga FAIV-förslag. Hook, caption, CTA, format, bildmapp, fallback-prompt, godkänd (ja/nej), använd (ja/nej). Mänsklig kontroll sker här.

**Asset Library** — enkel katalog över Drive-bildbanken. Mapp, filnamn, kategori, nyckelord.

**Run Log** — en rad per körning. Datum, antal hämtade, antal kandidater, antal förslag, fel och varningar, e-poststatus.

---

## Google Drive bildbank

Skapa mappstruktur manuellt en gång:

```
FAIV-bildbank/
  grillkit/
  extrabelysning/
  arbetsljus/
  bilinredning/
  servicebilar/
  husbil-offgrid/
  verkstad/
  kundbyggen/
```

Lägg bilder i rätt mapp. Namnge filer beskrivande, t.ex. `grillkit-volvo-fh-monterad.jpg`. Asset Library-fliken fylls med ett engångsskript. Uppdateras manuellt när nya bilder tillkommer.

---

## GitHub-repo

```
faiv-social/
  .github/workflows/
    daily_run.yml        # cron 07:00 Stockholm, mån–fre
  src/
    collect.py           # Apify-anrop
    analyze.py           # OpenRouter scoring
    propose.py           # OpenRouter FAIV-omskrivning
    assets.py            # bildmatchning på mappnivå
    deliver.py           # Google Doc + e-post
    sheets.py            # all Sheet-kommunikation
    config.py            # läser Settings-fliken
  tests/
    test_scoring.py
    test_parser.py
    test_assets.py
```

Secrets (sätts en gång i GitHub, rör aldrig igen):

- `APIFY_TOKEN`
- `OPENROUTER_API_KEY`
- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `NOTIFY_EMAIL`

---

## Steg 4 — Insamling

`collect.py` läser Sources, identifierar aktiv batch (A/B/C roterar automatiskt baserat på datum), hämtar ~29 konton via Apify HTTP-only Instagram Post Scraper.

Throttle 2–3 sekunder per konto med jitter. Vid rate-limit: markera konto blockerat, fortsätt. Dedup mot Collected Posts via post-URL. Hela körningen tar under 5 minuter.

---

## Steg 5 — Analys och scoring i ett anrop

Alla nya poster från dagens batch skickas i **ett enda strukturerat anrop** till OpenRouter. Modellen returnerar JSON med scoring per post.

Prompt-struktur:

```
Du är FAIVs innehållsanalytiker. Bedöm dessa Instagram-poster
för hur väl de kan bli svenska FAIV-inlägg.

FAIV säljer: grillkit, extrabelysning, arbetsljus, bilinredning,
servicebilar, husbil/offgrid till svenska fordonsägare.

Returnera JSON-array med ett objekt per post:
{
  "url": "...",
  "faiv_fit": 0-30,
  "lead_potential": 0-25,
  "hook_strength": 0-20,
  "visual_transferability": 0-15,
  "novelty": 0-10,
  "total": 0-100,
  "faiv_category": "grillkit|extrabelysning|...",
  "why_it_works": "...",
  "originality_risk": "låg|medel|hög"
}

Poster att bedöma:
[lista med caption + metadata per post]
```

Batchar om 20 poster per anrop för att hålla token-kostnaden nere.

---

## Steg 6 — FAIV-omskrivning

`propose.py` tar topp 5 från Candidates och skickar **ett samlat anrop** till OpenRouter med alla fem poster.

Output per förslag:
- hook (max 2 rader svenska)
- caption (max 120 ord svenska)
- CTA (offert- eller kontaktuppmaning)
- format (enkelbild / karusell / reel-koncept)
- bildbrief (exakt beskrivning)
- rekommenderad bildmapp
- fallback AI-bildprompt
- varför idén valdes

---

## Steg 7 — Bildmatchning

`assets.py` matchar FAIV-kategori mot Drive-mapp. Returnerar mappnamn + antal tillgängliga bilder. Confidence baseras på hur många bilder som finns — under 3 bilder i mappen ger automatiskt AI-bildprompt istället.

---

## Steg 8 — Leverans

Google Doc skapas om minst 3 förslag genererats. E-post skickas alltid — lyckat eller misslyckat — med länk till Doc och Run Log-sammanfattning.

Felmeddelanden på svenska med instruktion, t.ex.:

> "Apify-krediter slut för månaden. Systemet startar om automatiskt den 1:a. Inget att göra."

> "OpenRouter-nyckel ogiltig. Gå till openrouter.ai → Keys → skapa ny nyckel → klistra in i GitHub Settings → Secrets → OPENROUTER_API_KEY."

---

## Byggordning

1. Google Sheet-struktur + Settings-flik + watchlist-import
2. Apify-insamling för en enda batch, verifiera data i Sheet
3. OpenRouter scoring med Gemini Flash, verifiera JSON-output
4. FAIV-omskrivning, verifiera att alla fält alltid är ifyllda
5. Bildmatchning mot Drive-mappar
6. Google Doc-generering och e-postleverans
7. Felhantering med svenska instruktioner
8. A/B/C-batchrotation för alla 87 konton
9. Tester och end-to-end-körning

---

## Vad du gör manuellt (en gång)

- Skapa GitHub-repo och lägg in 4 secrets
- Skapa Drive-mappstruktur och lägg bilder i rätt mappar
- Importera Excel-watchlist till Sources-fliken
- Sätt e-postadress i Settings-fliken

**Därefter: öppna Google Doc varje morgon, läs 5 förslag, använd de du gillar.**
