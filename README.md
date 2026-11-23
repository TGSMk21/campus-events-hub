# Campus Event and Activities Hub

ICT461 Advanced Web Technologies, Mulungushi University (Group 2).

## Lab 2: Accessible venue booking request form

`lab2/` contains a standards-compliant, WCAG 2.2 AA front-end for the organizer venue booking request form:

- Semantic HTML5 landmarks and explicitly labelled form controls
- High-contrast colours and visible focus indicators
- Real-time validation with `aria-invalid`, `aria-describedby` and an `aria-live` summary
- Lighthouse accessibility score 100; axe-core reports zero violations

Run it locally:

```bash
cd lab2
python -m http.server 8000
# open http://localhost:8000
```

## Final product demo (`site/`)

A no-install concept demo of the full Campus Event & Activities Hub: plain HTML, CSS and JavaScript, with no build step and no server.

- **View as Student / Organizer / Admin** using the switcher in the header (stands in for login and role-based access).
- **Students:** search and filter events, follow clubs, get recommendations, register for free events or buy tickets through a simulated mobile-money checkout, and join a live event chat.
- **Organizers:** create events with the accessible Lab 2 form (real-time validation), request a venue (clashes are flagged immediately) and attach approval letters.
- **Admins:** approve or reject venue requests. Approving a booking that overlaps an approved one is blocked, and the outbox shows the simulated email and WhatsApp notifications.
- **Live updates:** open the site in two tabs. Tickets, approvals and chat sync instantly, standing in for WebSockets.
- Data is saved in the browser; **Reset demo data** in the banner restores the starting state.

Run locally:

```bash
cd site
python3 -m http.server 8000
# open http://localhost:8000
```

Deploy to Vercel: import the GitHub repo at vercel.com/new, set **Root Directory** to `site`, Framework Preset **Other**, and deploy. No build command is needed. `site/vercel.json` adds security headers.
