# Manual scenario presets implementation plan

Design: [Technical design](../../technical-design.md).

1. Add a three-option selector before starting a browser session, with a date field for the guide shortage.
2. Apply the selected inventory and guide conditions per session in mock and in the bundled HTTP demo. Preserve CLI defaults and external operator ownership.
3. Test the selector API, mock/HTTP parity, date specificity and isolation between sessions.
