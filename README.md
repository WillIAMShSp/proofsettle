# Welcome to your Lovable project

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Open your project in the [Lovable editor](https://lovable.dev) and keep building.

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: connect the project to GitHub and every change made in Lovable is committed straight to your repository.
- **Full ownership**: this code is yours. Push to your repository and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

## Built with

- TanStack Start
- TypeScript
- React
- Tailwind CSS

## Solana anchoring

The FastAPI backend (`backend/`) can mirror every shipment's audit trail onto the ProofSettle
Solana program (`programs/proofsettle/`, see its README). The database stays the source of
truth. After each write, the backend sends the matching program instruction and stores the
transaction signature on the audit event. The shipment page then links each event to
Solana Explorer, and "Verify hashes" also checks the database against the on-chain record.
Anchoring is off until it's configured, and if the RPC is down the app keeps working.

To turn it on (devnet; run from `backend/`):

```bash
uv run python -m app.chain keygen .solana        # four demo keys; prints the .env lines
# add those lines plus PROOFSETTLE_SOLANA_RPC_URL=https://api.devnet.solana.com to
# backend/.env (git-ignored; the root .env is committed, so keep keys out of it)
uv run python -m app.chain fund --from ~/.config/solana/id.json --sol 0.2
uv run python -m app.chain status                # balances and each shipment's state
uv run uvicorn app.main:app                      # anchors pending history on startup
```

| Setting | Meaning |
|---|---|
| `PROOFSETTLE_SOLANA_RPC_URL` | JSON-RPC endpoint; anchoring is off when empty |
| `PROOFSETTLE_SOLANA_{BUYER,SUPPLIER,AUTHORITY,REVIEWER}_KEYPAIR` | Keypair file path, or the keypair's JSON array. Server-side only |
| `PROOFSETTLE_SOLANA_PROGRAM_ID` | Defaults to the address in `backend/app/chain/proofsettle.json` |
| `PROOFSETTLE_SOLANA_SHIPMENT_SALT` | Change after `POST /dev/reset`, so reseeded shipments get fresh on-chain accounts |
| `PROOFSETTLE_SOLANA_EXPLORER_CLUSTER` | Explorer link cluster, default `devnet` |

The backend signs for all four parties with server-held demo keys. That's fine for a devnet
demo, but those signatures don't prove each party's own consent (`backend/CHAIN_ALIGNMENT.md`
§5).
