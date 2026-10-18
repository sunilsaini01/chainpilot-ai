# Manual accessibility check (P9-T5)

Automatic checks (axe, WCAG 2.1 A and AA, on every page) and a keyboard-only browser test (`apps/web/e2e/keyboard.spec.ts`) already pass. This is the **human** part: listening to the dashboard with a screen reader. It closes review item P6-T4-R3.

**Tools:** Windows **Narrator** (built in). Start or stop it with **Ctrl + Windows + Enter**. Narrator's key is **Caps Lock**. **Caps Lock + Space** switches *scan mode* on and off; in scan mode **H** jumps to the next heading and **T** to the next table. Use the local demo at http://127.0.0.1:8080 and one of the demo logins from `scripts/demo-setup.sh`.

| # | Do this | Narrator should say (about) | Result |
|---|---|---|---|
| 1 | Open the login page | "ChainPilot AI" and "Simulated data" | |
| 2 | Press Tab | "Email, edit" | |
| 3 | Press Tab | "Password, edit" (protected) | |
| 4 | Press Tab | "Log in, button" | |
| 5 | Type a wrong password and press Enter | "Incorrect email or password." (read out by itself) | |
| 6 | Log in as **demo-manager**, then in scan mode press H | "Overview, heading level 1", then the section headings (Stock, Stock-out risk, …) | |
| 7 | Leave scan mode, press Tab through the menu | "Overview, link", "Stock risks, link", "Approval queue, link", … | |
| 8 | Open **Approval queue**, Tab to the first Approve button | "Approve transfer … × SYN-… from SYN-WH… to SYN-WH…, button" (says *which* row) | |
| 9 | In scan mode press T, then Ctrl + Alt + arrow keys in the table | Column names (Kind, SKU, To warehouse, …) with each cell | |
| 10 | Press Enter on an Approve button, then OK in the confirmation | The confirmation question is read; afterwards "… placed …" or "… stock moved" is read by itself | |
| 11 | Open **Ask the copilot**, Tab to the text box | "Your question, edit" | |
| 12 | Open **Stock risks**, Tab to the filters | "Warehouse, combo box" and "Status, combo box" | |

**Result:** _(to be filled in from the owner's walkthrough)_
