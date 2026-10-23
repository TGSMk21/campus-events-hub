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
