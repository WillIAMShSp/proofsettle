# Proofsettle

Visual theme: Solana-inspired dark UI. Use a near-black background (#0B0B0F) with slightly lighter card surfaces (#14141A), thin low-contrast borders, and white text with muted gray secondary text. Use Solana's signature gradient (purple #9945FF to green #14F195) sparingly, only on the primary CTA, the hero headline accent, active stepper states, and key highlights. Use green #14F195 for success and verified states, purple #9945FF for primary actions, amber for "Needs review," and red for disputes. Typography is large and clean (Inter), with a monospace font (JetBrains Mono) for hashes and wallet-style IDs. Use rounded-2xl cards, soft purple glows on hover, and subtle fade or slide-in motion only. Keep the layout minimal with generous spacing. No clutter, no emojis, no gradient-filled backgrounds across whole sections.

I've also attached the PRD for ProofSettle ("Payments backed by agreed evidence"), a B2B settlement platform for the HackGB Industrial track. I'm building FRONT END ONLY. Use mock data and a fake login for now. No backend, no database, no real blockchain, no real AI calls. Keep all state in memory or localStorage. Do not add Supabase or any integrations.

Stack: React, TypeScript, Tailwind. Keep the code compact and avoid generating extra files, docs, or tests.

BUILD IN THIS ORDER, and keep this first pass to the items below only:
Landing page (Apple-style): minimal nav, big hero with the tagline "Payments backed by agreed evidence," one primary CTA ("Open demo") that goes to a fake login, a short three-step section (Agree → Inspect → Settle), and a simple footer.
Fake login: one screen with two demo buttons, "Continue as Buyer" and "Continue as Supplier." Store the role in state and show it in the top bar.
Dashboard: a clean list of shipments with status chips (Draft, Agreed, In Transit, Inspection, Proposed, Accepted, Disputed, Resolved). Seed it with 3 mock shipments, including the main demo: "100 metal components, $10,000."
Shipment detail page for the main demo with a status stepper across the top and these sections:
Agreement: terms, $100 credit per confirmed defective component, and both-party approval badges
Evidence: dispatch and receipt photo grids (use placeholder images), each with a truncated SHA-256 hash and a "Verified" check
AI Inspection: findings as cards (item, confidence score, "Needs review" flag when confidence is low) and a note that AI cannot prove when or where damage occurred
Proposed Adjustment: show the rule applied (3 defects × $100 = $300), assumptions, and uncertainty
Decision: the Supplier sees Accept and Dispute buttons (Dispute requires a reason). The Buyer sees read-only status.
Audit Trail: a simple timeline of events with a "Verify hashes" button that shows a success state
Key rule to show in the UI: AI never decides the payment amount. The amount always comes from the agreement rules.

Do NOT build yet: agreement creation form, invoice parsing, blockchain UI, settings, notifications, or extra pages. I'll request those in follow-up prompts.

Before writing code, give me a short plan (under 10 lines), then build.

This project was built with [Lovable](https://lovable.dev).

**Live app**: https://proofsettle.lovable.app

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/5917b357-b543-483a-8953-41a88076b3ac).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
