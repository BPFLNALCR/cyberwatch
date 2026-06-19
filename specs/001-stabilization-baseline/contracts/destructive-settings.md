# Contract: Destructive Settings Guard

## Scope

Applies to:

- `POST /settings/clear-measurements`
- `POST /settings/clear-dns`
- `POST /settings/clear-graph`
- `POST /settings/clear-all`

## Environment Control

`CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS`

Default: disabled when unset.

Enabled values:

- `1`
- `true`
- `yes`
- `on`

Comparison is case-insensitive after trimming whitespace.

## Disabled Response

When disabled, the endpoint must reject the request before any destructive work starts.

Expected response style:

- HTTP status: `403`
- Detail/message: destructive settings endpoints are disabled and can be enabled by setting `CYBERWATCH_ENABLE_DESTRUCTIVE_SETTINGS=true`.

## Enabled Behavior

When enabled, existing route behavior remains available:

- measurement clear truncates measurement-related data
- DNS clear truncates DNS-related data
- graph clear removes graph nodes and relationships
- clear-all performs the existing combined clear behavior

## Validation

- Unit tests cover unset, false-like, and true-like env values.
- Unit tests verify the guard raises/rejects before route work can continue when disabled.

