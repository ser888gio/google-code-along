# GCP Authentication — Local Docker Setup

Follow these steps once before running `docker compose up` for the first time.

---

## Step 1 — Install Google Cloud CLI

If you don't have `gcloud` installed yet:

1. Download from https://cloud.google.com/sdk/docs/install
2. Run the installer and follow the prompts
3. Open a new terminal and verify:

```bash
gcloud --version
```

---

## Step 2 — Log in to Google Cloud

```bash
gcloud auth login
```

- A browser window opens
- Sign in with your Google account that has access to project `vw-skda-fhackton-156`
- Approve the permissions

---

## Step 3 — Set the active project

```bash
gcloud config set project vw-skda-fhackton-156
```

---

## Step 4 — Generate Application Default Credentials (ADC)

This is what the backend uses to call Vertex AI, GCS, and Firestore:

```bash
gcloud auth application-default login
```

- Another browser window opens — approve again
- This writes a credentials file to your machine:
  - **Windows:** `%APPDATA%\gcloud\application_default_credentials.json`
  - **macOS / Linux:** `~/.config/gcloud/application_default_credentials.json`

---

## Step 5 — Copy the credentials file to the project root

**Git Bash / WSL / macOS / Linux:**
```bash
cp "$APPDATA/gcloud/application_default_credentials.json" gcp-key.json
```

**Windows CMD:**
```cmd
copy "%APPDATA%\gcloud\application_default_credentials.json" gcp-key.json
```

**Windows PowerShell:**
```powershell
Copy-Item "$env:APPDATA\gcloud\application_default_credentials.json" gcp-key.json
```

The file should appear at the root of the repo next to `docker-compose.yml`.

> `gcp-key.json` is listed in `.gitignore` — it will never be committed.

---

## Step 6 — Start the stack

```bash
docker compose up --build
```

| Service  | URL                    |
|----------|------------------------|
| Frontend | http://localhost:3000  |
| Backend  | http://localhost:8080  |

---

## Troubleshooting

**`IsADirectoryError: /tmp/gcp-credentials.json`**
The `gcp-key.json` file is missing from the project root. Repeat Step 5.

**`No API key was provided`**
The `.env` file is missing `GOOGLE_GENAI_USE_VERTEXAI=1`. Check `backend/.env`.

**`Permission denied` on GCS / Firestore / Vertex AI**
Your account may not have the required IAM roles on the project. Ask the project owner to grant:
- `roles/aiplatform.user`
- `roles/storage.objectAdmin`
- `roles/datastore.user`
