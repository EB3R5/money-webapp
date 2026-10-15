# Edits persist a dirty-diff of changed fields; values keep their source typing

_Status: the source-typing half is superseded by ADR-0012 (2026-09-21); the dirty-diff rule stands._

Card-editor saves send only the fields the user actually changed, and the update endpoint `$set`s
exactly those. Values are stored as trimmed strings, matching the spreadsheet-backed schema
(ADR-0001); numeric inputs render as `type="text"` with `inputmode`, not `type="number"`.

Both choices come from a real bug: editing one field of an inventory item wiped `Unit_Cost` to
empty. A `type="number"` input silently blanks any stored value the browser deems invalid, and a
whole-object save then wrote that blank back. Sending a dirty-diff means an untouched field can
never be overwritten regardless of how the input behaves; text inputs avoid the silent blanking.

_Consequence:_ the client must track each field's original value to compute the diff. This is the
deliberate reason edit endpoints accept a partial body rather than a full document — don't
"simplify" them to require all fields.
