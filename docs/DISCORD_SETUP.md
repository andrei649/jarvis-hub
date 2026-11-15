# Discord native commands

The optional `discord.py` adapter uses the existing configured bot token. When
the configured channel starts, it creates application commands from Nerva's
canonical command registry and synchronizes them after the bot connects. No
command registration occurs merely by importing the module or reading settings.
The bot application's installation must include the `applications.commands`
scope and the channel permissions needed for its normal replies. This local
implementation has been tested offline with discord.py 2.6.4; live installation
and command propagation still need operator acceptance.

Each command accepts an optional `text` argument containing its ordinary command
arguments. Native commands show a private receipt, then use the same pairing,
access rules and approval queue as typed commands. A receipt does not mean the
command was authorized or executed. Replies arrive through normal channel
delivery. Native commands never answer an outstanding free-text clarification.

Discord's 100-command budget is applied to canonical built-ins first. Aliases
remain usable as typed commands. Channel health reports
`native_commands_registered`, `native_commands_hidden` and
`native_commands_synced`; registration failure leaves synchronization false.
Reconnects in the same adapter generation do not repeat a successful sync.
Plugin and skill command namespaces are not implemented in this slice.

Built-ins and their aliases take precedence over same-name skill bundles. Use
`/bundle NAME` explicitly to select such a bundle.
