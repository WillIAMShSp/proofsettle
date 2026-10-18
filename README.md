# ProofSettle

**Tamper-evident audit trails for real-world shipment inspections, anchored on Solana.**

ProofSettle links physical inspection evidence (photos + metadata) to public, verifiable proofs on Solana. Full records stay off-chain for privacy and usability, while a cryptographic fingerprint of each record is anchored on-chain for immutability and independent verification.

---

## The Problem

Physical shipment inspections and handoffs produce evidence (photos, notes, timestamps) that is easy to alter, lose, or dispute. Centralized logs can be modified after the fact and can't be independently verified by third parties, which makes disputes over condition, custody, and delivery hard to resolve.

## Our Solution

1. **Capture** an inspection (photo + metadata).
2. **Hash** the payload with a cryptographic hash function.
3. **Anchor** the hash in a lightweight Solana transaction.
4. **Store** the transaction signature alongside the record in the database.
5. **Verify** anytime: anyone can recompute the hash and compare it to the on-chain anchor via Solana Explorer.

If a record is changed after anchoring, its hash no longer matches the on-chain proof, so tampering is detectable.

## How It Works

```
┌──────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐
│  Web/Mobile  │───▶│   FastAPI    │───▶│ Solana Program  │───▶│   Solana     │
│  (React/TS)  │    │   Backend    │    │     (Rust)      │    │  Blockchain  │
└──────────────┘    └──────┬───────┘    └─────────────────┘    └──────┬───────┘
                           │                                          │
                           ▼                                          │
                    ┌──────────────┐        tx signature              │
                    │  PostgreSQL  │◀─────────────────────────────────┘
                    │ (full record │
                    │ + signature) │
                    └──────────────┘
```

1. A user captures a photo and fills out the inspection form in the web/mobile frontend.
2. The frontend uploads the data to the FastAPI backend.
3. The backend hashes the payload. **Only the fingerprint is published; raw data never leaves the database.**
4. The backend sends an instruction to the Solana program, which records or references the hash. Solana returns a transaction signature.
5. The backend stores the record together with the signature and provides a verification link (Solana Explorer + local hash comparison).
6. *(Optional)* Images can be run through an automated inspection/analysis pipeline using the Gemini API, before or after anchoring.

## Key Features

- **Privacy + immutability:** photos and notes stay off-chain; only hashes are public.
- **Usability:** a familiar web flow and standard database search for everyday operations.
- **Independent verifiability:** third parties can confirm a record's authenticity using the anchored transaction signature.
- **Extensible:** supports automated inspection plugins (e.g., Gemini), multi-party workflows, and batching strategies.

## Use Cases

- High-value freight (electronics, luxury goods)
- Cold-chain condition verification (pharma, food)
- Customs and third-party inspections
- Proof-of-delivery and chain-of-custody audits

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | TypeScript, React, Tailwind CSS |
| Backend | Python, FastAPI |
| On-chain program | Rust, Solana |
| Database | PostgreSQL (with small PL/pgSQL components) |
| AI analysis (optional) | Gemini API |

## Getting Started

> **Note:** Update the commands, directory names, and environment variables below to match the repo.

### Prerequisites

- Node.js 18+ and npm/yarn/pnpm
- Python 3.10+
- PostgreSQL
- Rust and the [Solana CLI](https://docs.solana.com/cli/install-solana-cli-tools)
- A funded Solana wallet on **devnet** (`solana airdrop 2`)
- *(Optional)* A Gemini API key

### 1. Clone the repo

```bash
git clone https://github.com/WillIAMShSp/proofsettle.git
cd proofsettle
```

### 2. Configure environment variables

Create a `.env` file in the backend directory (and frontend, if needed):

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/proofsettle

# Solana
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_PROGRAM_ID=<your_deployed_program_id>
SOLANA_PRIVATE_KEY=<backend_signing_keypair>   # keep secret, never commit

# Optional: automated inspection
GEMINI_API_KEY=<your_gemini_api_key>
```

### 3. Deploy the Solana program

```bash
cd <program-directory>
cargo build-sbf
solana program deploy target/deploy/<program_name>.so --url devnet
```

Copy the resulting program ID into your `.env`.

### 4. Run the backend

```bash
cd <backend-directory>
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### 5. Run the frontend

```bash
cd <frontend-directory>
npm install
npm run dev
```

The app should now be running locally.

## Demo Walkthrough

1. **Create** a shipment record.
2. **Run an inspection:** upload a photo and add notes.
3. The backend **hashes** the payload and **anchors** it on Solana.
4. View the database record, which now includes the **transaction signature**.
5. Open **Solana Explorer** to see the anchored transaction.
6. **Verify:** recompute the hash of the stored record and confirm it matches the on-chain anchor.

## Security & Privacy

- Only cryptographic hashes are anchored on-chain. Photos and notes remain private in the database.
- Anchoring happens immediately when an inspection is completed, minimizing the window for tampering.
- Backend logs and careful key management further reduce risk.
- **Never commit private keys or `.env` files.** Use a secrets manager in production.

## Roadmap

- [ ] Mobile-first camera UX and SDK
- [ ] Multi-party signing and dispute resolution UI
- [ ] Hardened key management
- [ ] Enterprise integrations
- [ ] Public verification API / marketplace

## Looking for Partners

We're seeking pilot partners in logistics and cold-chain, mentorship on taking ProofSettle enterprise-ready, and support to build mobile SDKs and hardened key management. If that's you, reach out!

## Team

**Team ProofSettle**

- *Name* — [email@example.com](mailto:email@example.com)
- *Name* — [email@example.com](mailto:email@example.com)

## License

*Add a license (e.g., MIT) before publishing.*

---

Built for [Hackathon Name]. Repo: [github.com/WillIAMShSp/proofsettle](https://github.com/WillIAMShSp/proofsettle)
