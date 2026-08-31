# Delta for Mail Get Detail

## MODIFIED Requirements

### Requirement: Get Message Input/Output

The `mail_get_message` tool MUST accept `entryId` (string, required) and
`includeHtmlBody` (boolean, optional, default `false`), and MUST return a
`MessageDetail` object with `entryId`, `subject`, `sender`, `senderAddress`,
`date`, `hasAttachments`, `to` (recipient names/addresses), `body`,
`attachmentNames` (list of strings), and `htmlBody`. `body` MUST always be
the plain-text `MailItem.Body`, never `HTMLBody`, regardless of
`includeHtmlBody`. `attachmentNames` MUST always be present: the display
name of each attachment when `hasAttachments` is true, or an empty list
when it is false; `hasAttachments` itself is unaffected by this change.
`htmlBody` MUST be `None`/omitted unless `includeHtmlBody=true` was passed,
in which case it MUST contain `MailItem.HTMLBody`.
(Previously: no `includeHtmlBody` input, no `htmlBody` or `attachmentNames`
output fields.)

#### Scenario: Successful fetch (backward-compatible default)

- GIVEN a fake adapter whose `get_message("MSG-1")` returns a `MessageDetail` with
  subject "Factura agosto", `sender="Ana Gómez"`, `to=["yo@example.com"]`, `body="Adjunto la factura."`, `attachment_names=["factura.pdf"]`
- WHEN `mail_get_message` is called with `entryId="MSG-1"` and `includeHtmlBody` omitted
- THEN the tool returns `subject`, `sender`, `senderAddress`, `date`, `to`, `hasAttachments`, `body`, and `attachmentNames=["factura.pdf"]` matching the adapter's result
- AND `htmlBody` is `None`/omitted

#### Scenario: includeHtmlBody=true returns the HTML body

- GIVEN a fake adapter whose `get_message("MSG-1")` returns a `MessageDetail` with `body="Adjunto la factura."` and `html_body="<p>Adjunto la factura.</p>"`
- WHEN `mail_get_message` is called with `entryId="MSG-1"`, `includeHtmlBody=true`
- THEN the tool returns `htmlBody="<p>Adjunto la factura.</p>"`
- AND `body` is still the plain-text `"Adjunto la factura."`, unchanged

#### Scenario: No attachments yields an empty attachmentNames list

- GIVEN a fake adapter whose `get_message("MSG-2")` returns a `MessageDetail` with `has_attachments=False`, `attachment_names=[]`
- WHEN `mail_get_message` is called with `entryId="MSG-2"`
- THEN the tool returns `attachmentNames=[]` and `hasAttachments=false`
