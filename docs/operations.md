# Operations guide

## Local development

```bash
python -m pip install -e ".[test]"
python -m pytest
python scripts/benchmark_core.py
```

The API requires FastAPI and can be started with:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

The frontend is developed separately with Node/npm:

```bash
cd frontend
npm install
npm run dev
```

## Production checklist

1. Use a dedicated Linux service account.
2. Keep `OBSERVE` mode until approval workflows are configured.
3. Configure the authorized restart set explicitly.
4. Configure SQLite retention and backup.
5. Bind the API to loopback or an authenticated reverse proxy.
6. Install and pin the selected Ollama model locally if AI diagnosis is needed.
7. Test recovery verification with a disposable Linux environment.
8. Review remediation audit records regularly.

## Offline operation

Runtime monitoring, persistence, rule diagnosis, remediation policy checks, and
verification do not require Internet access. Package installation and frontend
builds are installation-time concerns, not runtime dependencies.
