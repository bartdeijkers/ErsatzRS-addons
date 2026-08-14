# Trakt Lists add-on

This add-on imports public Trakt user lists through ErsatzRS'
`media-list.list.v1` contract. Configure `CLIENT_ID` as an environment or file
secret reference in the ErsatzRS add-on settings. The manifest suggests the
existing `TRAKT__CLIENTID` environment-variable name, but ErsatzRS stores only
that reference name and never copies the credential into its database.

The preferred form is `https://trakt.tv/users/<user>/lists/<slug>`. For
ErsatzTV compatibility, `app.trakt.tv` links, the older `/users/<user>/<slug>`
and `/lists/<user>/<slug>` paths, and `<user>/[lists/]<slug>` shorthand are also
accepted. Only public lists can be imported.

The package contains a native Rust executable for every ErsatzRS release RID.
It does not require Python or another operator-installed runtime.
