# FAIV Sociala Medier

Budgetoptimerad pipeline för att bevaka inspirationskonton, välja ut relevanta poster och skriva om dem till f\u00e4rdiga FAIV-f\u00f6rslag i Google Drive.

Nuvarande lagringsstruktur:

- Cloudflare R2 f\u00f6r full r\u00e5arkivering av Apify-svar
- Cloudflare D1 f\u00f6r live metadata, kandidater, f\u00f6rslag och run-historik
- Google Sheets/Docs som kontrollpanel och redakt\u00f6rsyta

## Kommandon

- python -m pip install .
- python -m src.main login \u2014 OAuth-inloggning mot Google (\u00f6ppnar browser, sparar token)
- python -m src.main bootstrap \u2014 skapar eller initierar Google Sheet-kontrollpanelen
- python -m src.main collect-only --handles f.a.i.v.ab --posts-per-account 5
- python -m src.main sync-assets
- python -m src.main run

Titta i r\u00e4tt lagringslager:

- D1 (collected_posts, candidates, proposals, 
uns) = live data f\u00f6r analys, queries och app-logik
- R2 (pify/raw/...json.gz) = full r\u00e5dump fr\u00e5n Apify f\u00f6r backfill, revision och framtida omtolkning

## Google-autentisering (OAuth)

Projektet anv\u00e4nder OAuth user-login, inte service account. Det inneb\u00e4r att filer skapas som din Google-anv\u00e4ndare i din Drive.

### F\u00f6rsta g\u00e5ngen (lokal maskin)

1. Skapa en OAuth client ID i Google Cloud Console (Desktop app-typ)
2. Ladda ner JSON-filen som client_secrets.json till projektroten
3. K\u00f6r python -m src.main login \u2014 \u00f6ppnar browser f\u00f6r inloggning
4. Token sparas i .google_token.json (gitignorad)

### F\u00f6r GitHub Actions (CI)

1. Inneh\u00e5llet i client_secrets.json \u2192 GitHub secret GOOGLE_CLIENT_SECRETS_JSON
2. Inneh\u00e5llet i .google_token.json \u2192 GitHub secret GOOGLE_TOKEN_JSON
3. Workflow-filen skriver dessa till filer innan pipelinen k\u00f6rs
4. Token f\u00f6rnyas automatiskt med refresh_token

## Minimikrav

- GitHub Actions secrets:
  - APIFY_TOKEN
  - OPENROUTER_API_KEY
  - GOOGLE_CLIENT_SECRETS_JSON
  - GOOGLE_TOKEN_JSON
  - GOOGLE_SPREADSHEET_ID
  - NOTIFY_EMAIL
- F\u00f6r Cloudflare-lagring:
  - R2_BUCKET
  - R2_ENDPOINT eller R2_ACCOUNT_ID
  - R2_ACCESS_KEY_ID
  - R2_SECRET_ACCESS_KEY
  - CLOUDFLARE_ACCOUNT_ID
  - CLOUDFLARE_API_TOKEN
  - CLOUDFLARE_D1_DATABASE_ID
- F\u00f6r e-postleverans (optional \u2014 pipelinen k\u00f6rs \u00e4ven utan):
  - SMTP_HOST
  - SMTP_PORT
  - SMTP_USERNAME
  - SMTP_PASSWORD
  - SMTP_FROM
