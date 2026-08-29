# wa-agent-starter

A small, working WhatsApp agent you run on your own server, on the official Meta
WhatsApp Cloud API. It answers frequently asked questions in **Hebrew, Arabic and
English**, and gets the right-to-left details right.

MIT licensed. No account with us, no hosted service, no telemetry. You own the
number, the Meta app and the server.

---

## What it actually does

- **Receives** WhatsApp messages through Meta's webhook (`GET` verification +
  `POST` delivery).
- **Verifies** every inbound POST against `X-Hub-Signature-256` (HMAC-SHA256 over
  the raw body). An unsigned or mis-signed request is refused.
- **Detects** the language of the message from its script, and answers in that
  language.
- **Matches** the message against a keyword intent file (`faq.json`) and sends
  the matching answer, or a fallback that lists what it can help with.
- **Fixes the two RTL bugs** that Hebrew and Arabic bots routinely ship with:
  phone numbers and links rendering backwards inside a sentence, and a whole
  line flipping to left-to-right because it happens to start with a digit.
- **Ignores redelivered messages**, so a slow reply does not answer the customer
  twice.

## What it is not

It has no memory, no retrieval over your documents, no human handover, no admin
panel, and no support for more than one business number. It answers what you
wrote a keyword for, and says "I didn't catch that" for everything else. That is
the honest boundary of a free starter; the paid kit at the bottom of this file
lists exactly what is on the other side of it.

---

## Install in 5 minutes

You need [Docker](https://docs.docker.com/get-docker/) and a Meta developer
account. Nothing else.

```bash
git clone https://github.com/YOUR-USERNAME/wa-agent-starter.git
cd wa-agent-starter
cp .env.example .env
```

Open `.env` and fill in the four Meta values (the next section says where each
one comes from). Then:

```bash
docker compose up --build
```

The webhook is now listening on `http://localhost:8000/webhook`, and
`http://localhost:8000/health` tells you how the instance is configured.

Prefer to run it without Docker:

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## Getting the Meta credentials

All four values come from one place: <https://developers.facebook.com/apps>.

1. **Create an app.** *Create App* -> type **Business** -> add the **WhatsApp**
   product to it.
2. **`WHATSAPP_PHONE_ID`** — *WhatsApp -> API Setup*. Copy the **Phone number
   ID**. It is a long number under the test phone number. Copy the ID, not the
   phone number itself.
3. **`WHATSAPP_TOKEN`** — the same page has a **temporary access token**, valid
   for 24 hours. That is enough for your first test. For anything permanent,
   create a **System User** in *Business Settings -> Users -> System Users*, give
   it the `whatsapp_business_messaging` and `whatsapp_business_management`
   permissions, and generate a token there.
4. **`META_APP_SECRET`** — *App settings -> Basic -> App Secret -> Show*. This is
   what signs every incoming webhook. Without it, this app refuses all traffic.
5. **`WHATSAPP_VERIFY_TOKEN`** — you invent this one. Any random string. You will
   paste the same value into Meta in the next step.

While your app is in development mode, Meta only delivers to numbers you added
to the test allow-list on the API Setup page. Add your own phone there first, or
your test messages go nowhere with no error.

### Pointing Meta at your server

Meta only calls a **public HTTPS** URL. Two ways to give it one:

- **Production:** put this container behind your reverse proxy (Caddy, Traefik,
  nginx) on a domain with a certificate.
- **While testing:** a tunnel such as `cloudflared tunnel --url
  http://localhost:8000` or `ngrok http 8000` gives you a temporary HTTPS
  address.

Then in the Meta app: *WhatsApp -> Configuration -> Edit* and enter

- **Callback URL:** `https://your-domain.example/webhook`
- **Verify token:** the exact `WHATSAPP_VERIFY_TOKEN` from your `.env`

Press **Verify and save**, then **Manage** and subscribe to the **messages**
field. Without that subscription the URL verifies but no message is ever
delivered — the single most common reason a new webhook looks dead.

---

## Try it without Meta

The repository includes a simulator that posts a correctly signed fake message,
so you can see the whole path work before any Meta setup.

First put **any** string in `META_APP_SECRET` in your `.env` — for this you are
not fetching Meta's real App Secret, you are only giving the app and the
simulator the same value to sign with. Leave it empty and the app refuses the
request, exactly as it refuses an unsigned one from anyone else. Then:

```bash
python scripts/simulate_webhook.py --text "what are your opening hours?"
python scripts/simulate_webhook.py --message-id wamid.2 --text "delivery?"
```

Change `--message-id` between runs, or the duplicate guard skips the second one.

With no `WHATSAPP_TOKEN` set, the app logs the reply instead of sending it. Watch
it with `docker compose logs -f agent`.

---

## Changing the answers

Everything the agent says lives in `faq.json` — nothing is hard-coded in Python.
Each intent has keywords per language and an answer per language:

```json
{
  "id": "hours",
  "keywords": { "he": ["..."], "ar": ["..."], "en": ["hours", "opening"] },
  "reply":    { "he": "...",   "ar": "...",   "en": "Opening hours: ..." }
}
```

Notes worth knowing:

- Keywords from **every** language are tried on **every** message, so an English
  keyword still matches for a Hebrew speaker. Only the *answer* follows the
  language the customer wrote in.
- The optional `"weight"` (default `1.0`) is why "Hello, what are your hours?"
  answers with the hours and not with a greeting. Keep greeting and thanks below
  `1.0`.
- Arabic spelling is normalised before matching (alef forms, ta-marbuta,
  alef-maqsura, diacritics, tatweel), and Arabic-Indic digits are folded to
  `0-9`, so you do not need a keyword per spelling.
- `docker compose` mounts `faq.json` from the host, so editing the file and
  restarting the container is enough.

## About the RTL handling

Two fixes, both pure text, in `app/rtl.py`:

1. Phone numbers, prices, URLs and e-mail addresses are wrapped in a
   **left-to-right isolate** (`U+2066 … U+2069`). Without it `+972-4-000-0000`
   can render as `0000-000-4-972+` inside a Hebrew or Arabic sentence, because
   the dashes are neutral characters that inherit the paragraph direction.
2. Any line that does not start with a strong RTL character gets an invisible
   **right-to-left mark** (`U+200F`), so a line beginning with a digit or a Latin
   word does not flip the whole paragraph's alignment.

English replies are returned untouched, so they never carry invisible control
characters.

## Running the tests

No test framework to install: `unittest` comes with Python, and the endpoint
tests use only what the app already depends on.

```bash
python -m unittest discover -s tests -t .
```

They cover signature rejection, language detection, RTL output, intent matching,
and the webhook endpoints themselves (the Meta handshake, the signature gate and
the health probe) driven through the real app.

---

## What the paid kit adds

This starter is deliberately complete for what it claims and deliberately
limited. **wa-agent-kit** is the full version, and these are the differences —
no other features are implied:

| | starter (free) | wa-agent-kit |
|---|---|---|
| Answers | keyword intents from a JSON file | **memory and retrieval**: a Qdrant vector store over your own documents, so it answers questions nobody wrote a keyword for, and remembers the conversation |
| Businesses per instance | one | **multi-tenant**: many numbers and many businesses on one deployment, isolated from each other |
| Escalation | tells the customer someone will follow up | **human handover**: the agent steps aside, a real person takes the thread, and it resumes afterwards |
| Operating it | container logs | **admin panel**: conversations, intents, what failed, and the answer book editable from the browser |
| Updates | whatever is on GitHub | **12 months of updates**, including Graph API version changes |
| Using it for clients | your own business only, under MIT | **client-deployment licence**: deploy it for paying clients (agency licence covers unlimited clients) |

Price: **$149** for the full kit, **$499** for the agency licence. A launch price
of $99 applies for the first 30 days after release. One payment, no subscription;
you self-host both, exactly like this starter.

The link is in this repository's **About** section.

## Licence

MIT — see [LICENSE](LICENSE). Use it commercially, fork it, ship it. No warranty.
