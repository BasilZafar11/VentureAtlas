# VentureAtlas

VentureAtlas helps founders research a business category in a city, inspect market evidence, and turn assumptions into validation plans. VentureAtlas is the active app.

## Available features

The ResearchScope research workspace is available at `/research-scope`, with its prepared report at `/research-scope/reports/sample`. It retains the paper/patent novelty workflow and adds ten integrity tools for publication updates, opposing findings, citation support, question precision, statistical planning, reproducibility packages, artifact audits, extraction reconciliation, multilingual discovery, and sensitive-data readiness. Integrity records are exportable and can be explicitly shared through the research workspace; Crossref metadata requests run only on explicit user actions.


Market reports combine competitor listings, review topics, news, trends and advertising evidence, with source links, evidence completeness, relevance review and planning tools. The existing research workspace supports directions, forums, autocomplete, events, jobs, shopping, hotels, flights, images and Scholar.

Completed reports now open a decision workspace with ten additional tools:

1. Evidence connection diagram with linked findings, assumptions and decisions.
2. Contradictory evidence review with source links and investigation outcomes.
3. Research gap assistant with logical-search budgets and suggested research forms.
4. Editable customer persona hypotheses, interview questions and validation status.
5. Private team workspaces with accounts, viewer/editor roles, shared tasks, comments and owner-approved decisions.
6. Market change digests comparing compatible saved reports and research runs.
7. Competitor offer comparison with sourced prices, currencies, billing periods and terms.
8. Regulatory readiness records with official-source links, verification and follow-up dates.
9. Experiment prioritization within cost/time budgets, with observed results.
10. Evidence-backed editable pitch with saved experiment results, Markdown download and browser print/PDF.


## Submission and release

[Public repository](https://github.com/BasilZafar11/VentureAtlas)


## Run locally

Use Python 3.12+ and Node 22+.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-lock.txt
Copy-Item backend/.env.example backend/.env
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --no-access-log
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open [VentureAtlas locally](http://127.0.0.1:5173). Default fixture mode creates explicitly synthetic reports without provider calls. Server-side `SERPAPI_KEY` and `LIVE_SERPAPI_ENABLED=true` enable live research. Provider keys belong on the server.

## Verification

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
cd ../frontend
npm test -- --run
npm run build
```

Personal planning records stay in this browser; JSON/Markdown exports provide a copy. Clearing browser storage loses these records. Authenticated team data is stored on the backend. A private team workspace does not change the source market report's existing visibility.

This is a local prototype. Live provider integration and hosted deployment have not been verified for this change. Team accounts have no password reset, email invitation or SSO; hosted operation requires HTTPS. Regulatory entries and persona hypotheses require user verification. Search indicators do not predict business success.
