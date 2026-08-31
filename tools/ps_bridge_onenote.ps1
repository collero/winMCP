# PowerShell OneNote COM bridge (add-onenote-adapter change, Phase 4).
#
# Deployed alongside tools/onenote_adapter.py's OneNoteAdapter, invoked as a
# pinned, absolute Windows PowerShell 5.1 child process -- the exact same
# spawn shape tools/ps_bridge_search.ps1 uses, via the shared
# tools/ps_bridge_transport.py::PsBridgeTransport:
#
#   C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile
#     -NonInteractive -ExecutionPolicy Bypass -File <this script's absolute
#     path>
#
# Windows Search's SystemIndex has zero `onenote:` items (spike-verified,
# see /mnt/c/usr/WinMCP/_spike_onenote.ps1's own "systemindex-onenote"
# check) -- OneNote.Application COM is the only route to OneNote content,
# not a fallback the way this bridge is for file search.
#
# Security model: this script is a DUMB EXECUTOR, same discipline as
# ps_bridge_search.ps1. It reads exactly one JSON object from stdin --
# {"op": "FindPages"|"GetHierarchy"|"GetPageContent"|"CreateNewPage"|
#  "UpdatePageContent", ...op-specific fields} -- and dispatches on "op"
# to the matching OneNote.Application COM method, passing the given
# fields verbatim. It performs NO allowlist/policy decisions of its own --
# tools/onenote.py (a later batch) resolves and checks
# onenote_writable_notebooks BEFORE ever sending a CreateNewPage/
# UpdatePageContent request, per design.md's "Allowlist enforcement point"
# decision. Write ops here receive only an opaque sectionId/pageId, never
# a notebook name.
#
# Output contract: JSON LINES on stdout, same shape as ps_bridge_search.ps1
# -- zero or more compact JSON row objects, each written and flushed as
# soon as it is ready, followed by a final sentinel line
# `{"done": true, "count": N}`. On failure (COM unreachable, unresolved
# page/section id, or any other error before/during the op): a single JSON
# object with an "error" key plus a nonzero exit code -- read by
# tools/onenote_adapter.py's PsBridgeTransportError message (via
# PsBridgeTransport's stderr-excerpt diagnostic suffix) to distinguish
# "not found"/"conflict" from a generic bridge failure (see that module's
# `_NOT_FOUND_MARKERS`/`_CONFLICT_MARKERS`) -- so error text for those two
# cases deliberately contains the substrings "not found" / "modified
# since"/"conflict" respectively.
#
# XML handling: per tools/onenote_adapter.py's `_extract_title_and_body`
# docstring (a deliberate deviation from this change's design.md Decision
# 7), this script does NOT extract a page's title/body text itself -- it
# returns the page's raw XML (`pageXml`) for GetPageContent/CreateNewPage/
# UpdatePageContent, and the Python side parses it (dynamic namespace
# detection, Title/OE/T + Outline/OEChildren/OE/T CDATA extraction) --
# that logic lives in exactly one place, and it is unit-testable there,
# unlike inside this script. This script DOES still parse XML for
# FindPages/GetHierarchy, but only to read simple `name`/`ID`/`dateTime`
# XML ATTRIBUTES off the hierarchy tree -- no CDATA/text-node extraction
# is involved for those two ops.
#
# Per-call OneNote.Application lifecycle: one COM instantiation per bridge
# invocation, matching design.md's "Bridge lifecycle" decision (COM
# instantiates in ~23ms per the spike -- never a persistent daemon).

$ErrorActionPreference = "Stop"

# Emit UTF-8 on stdout regardless of the host's OEM codepage -- OneNote
# notebook/section/page names carry accented characters, and the Python
# side (PsBridgeTransport) decodes the stream as UTF-8. Without this pin,
# non-ASCII bytes left in the console codepage truncated the JSON-Lines
# stream at the first accented section name (live-QA defect). Set BEFORE
# the first [Console]::Out access so the writer is created with it. The
# no-BOM encoding keeps the first stdout line byte-identical to ASCII for
# ASCII-only rows.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

function ConvertTo-IsoStringOrNull($value) {
    # OneNote hierarchy/page XML carries dateTime as ISO-8601 STRING
    # attributes (e.g. "2026-08-27T08:15:00.000Z"), not [DateTime] --
    # calling .ToString("o") on a string throws (no such overload) and
    # skipped every FindPages/GetPageContent row (live-QA defect). Parse
    # strings round-trip-invariantly; pass real [DateTime] through; treat
    # empty/unparseable as null rather than killing the row.
    if ($null -eq $value) { return $null }
    if ($value -is [DateTime]) { return $value.ToString("o") }
    $text = [string]$value
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    try {
        return [DateTime]::Parse(
            $text,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind
        ).ToString("o")
    } catch {
        return $null
    }
}

function Get-HierarchyXml($OneNote) {
    $xmlStr = ""
    $OneNote.GetHierarchy("", 4, [ref]$xmlStr)
    [xml]$hier = $xmlStr
    $nsUri = $hier.DocumentElement.NamespaceURI
    $ns = New-Object System.Xml.XmlNamespaceManager($hier.NameTable)
    $ns.AddNamespace("one", $nsUri)
    return @{ Doc = $hier; Ns = $ns; NsUri = $nsUri }
}

function Resolve-SectionAncestors($hierarchy, [string]$sectionId) {
    # Returns @{ NotebookName = ...; SectionName = ... } for a section
    # node's own ID, or $null if it does not resolve -- used by
    # CreateNewPage, whose caller already resolved sectionId from a
    # notebook/section NAME pair at the tool layer, but this bridge is a
    # dumb executor and re-derives the names it needs to echo back in its
    # response row rather than trusting anything from the caller beyond
    # the opaque ID.
    $section = $hierarchy.Doc.SelectSingleNode("//one:Section[@ID='$sectionId']", $hierarchy.Ns)
    if (-not $section) { return $null }
    $notebook = $section.SelectSingleNode("ancestor::one:Notebook[1]", $hierarchy.Ns)
    return @{
        NotebookName = $(if ($notebook) { $notebook.name } else { "" })
        SectionName  = $section.name
        NotebookId   = $(if ($notebook) { $notebook.ID } else { "" })
        SectionId    = $section.ID
    }
}

function Resolve-PageAncestors($hierarchy, [string]$pageId) {
    # Same idea as Resolve-SectionAncestors, but starting from a page's
    # own ID -- used by GetPageContent/CreateNewPage/UpdatePageContent to
    # populate the response row's notebookName/sectionName without ever
    # exposing a notebook name to the caller as an INPUT. Also carries the
    # ancestors' IDs (onenote/0003 defect 2): the section id is the value
    # CreateNewPage requires and nothing else in the tool surface returned
    # it, so callers had to guess at OneNote's object-id grammar.
    $page = $hierarchy.Doc.SelectSingleNode("//one:Page[@ID='$pageId']", $hierarchy.Ns)
    if (-not $page) { return $null }
    $section = $page.SelectSingleNode("ancestor::one:Section[1]", $hierarchy.Ns)
    $notebook = $page.SelectSingleNode("ancestor::one:Notebook[1]", $hierarchy.Ns)
    return @{
        NotebookName = $(if ($notebook) { $notebook.name } else { "" })
        SectionName  = $(if ($section) { $section.name } else { "" })
        NotebookId   = $(if ($notebook) { $notebook.ID } else { "" })
        SectionId    = $(if ($section) { $section.ID } else { "" })
    }
}

function Get-PageXmlLastModified([xml]$px) {
    # THE timestamp that matters for writes (onenote/0002, live-confirmed
    # by prediction test): `UpdatePageContent` compares its
    # dateExpectedLastModified for EQUALITY against the page XML root's
    # own `lastModifiedTime` attribute -- NOT against the hierarchy's
    # `dateTime`/`lastModifiedTime` page attributes, which OneNote leaves
    # stale indefinitely once a page's write settles (observed 24h+ and
    # 19m53s apart on the same page). Reading the hierarchy here handed
    # every caller a value COM could never accept. Falls back to the
    # hierarchy value only when the page XML carries no attribute at all.
    $value = $px.DocumentElement.GetAttribute("lastModifiedTime")
    if ([string]::IsNullOrWhiteSpace($value)) { return $null }
    return $value
}

function Write-Row($stdout, $row) {
    $stdout.WriteLine((ConvertTo-Json -InputObject ([pscustomobject]$row) -Compress -Depth 6))
    $stdout.Flush()
}

try {
    $requestJson = [Console]::In.ReadToEnd()
    $request = $requestJson | ConvertFrom-Json
    $op = $request.op

    if ([string]::IsNullOrEmpty($op)) {
        throw "No 'op' field present in the stdin request"
    }

    $stdout = [Console]::Out
    $count = 0

    $onenote = New-Object -ComObject OneNote.Application

    switch ($op) {

        "FindPages" {
            $query = $request.query
            $findXml = ""
            $onenote.FindPages("", $query, [ref]$findXml, $false, $false)
            [xml]$fx = $findXml
            $nsUri = $fx.DocumentElement.NamespaceURI
            $ns = New-Object System.Xml.XmlNamespaceManager($fx.NameTable)
            $ns.AddNamespace("one", $nsUri)
            $pages = $fx.SelectNodes("//one:Page", $ns)
            foreach ($page in $pages) {
                try {
                    $section = $page.SelectSingleNode("ancestor::one:Section[1]", $ns)
                    $notebook = $page.SelectSingleNode("ancestor::one:Notebook[1]", $ns)
                    # lastModifiedTime, not dateTime: the hierarchy's
                    # `dateTime` page attribute is the CREATION time
                    # (onenote/0003 -- it never moved across landed
                    # writes). Note even lastModifiedTime here is
                    # hierarchy-sourced and can lag the page XML's own
                    # value -- onenote_get_page is the write-grade read.
                    $lm = $page.lastModifiedTime
                    if ([string]::IsNullOrWhiteSpace([string]$lm)) { $lm = $page.dateTime }
                    Write-Row $stdout @{
                        pageId       = $page.ID
                        title        = $page.name
                        notebookName = $(if ($notebook) { $notebook.name } else { "" })
                        sectionName  = $(if ($section) { $section.name } else { "" })
                        notebookId   = $(if ($notebook) { $notebook.ID } else { "" })
                        sectionId    = $(if ($section) { $section.ID } else { "" })
                        lastModified = ConvertTo-IsoStringOrNull $lm
                    }
                    $count++
                } catch {
                    [Console]::Error.WriteLine("row skipped: $($_.Exception.Message)")
                    continue
                }
            }
        }

        "GetHierarchy" {
            $hierarchy = Get-HierarchyXml $onenote
            $sections = $hierarchy.Doc.SelectNodes("//one:Section", $hierarchy.Ns)
            foreach ($section in $sections) {
                try {
                    $notebook = $section.SelectSingleNode("ancestor::one:Notebook[1]", $hierarchy.Ns)
                    Write-Row $stdout @{
                        notebookId   = $(if ($notebook) { $notebook.ID } else { "" })
                        notebookName = $(if ($notebook) { $notebook.name } else { "" })
                        sectionId    = $section.ID
                        sectionName  = $section.name
                    }
                    $count++
                } catch {
                    [Console]::Error.WriteLine("row skipped: $($_.Exception.Message)")
                    continue
                }
            }
        }

        "GetPageContent" {
            $pageId = $request.pageId
            $pageXml = ""
            try {
                $onenote.GetPageContent($pageId, [ref]$pageXml, 0)
            } catch {
                throw "page not found: $pageId ($($_.Exception.Message))"
            }
            if ([string]::IsNullOrEmpty($pageXml)) {
                throw "page not found: $pageId (empty content)"
            }
            [xml]$px = $pageXml
            $hierarchy = Get-HierarchyXml $onenote
            $ancestors = Resolve-PageAncestors $hierarchy $pageId
            # lastModified comes from the PAGE XML's own attribute -- the
            # one value a subsequent UpdatePageContent will accept -- never
            # from the hierarchy, whose page attributes go stale and even
            # report CREATION time under a last-modified name
            # (onenote/0002+0003; the hierarchy is only a fallback when
            # the page XML carries no attribute).
            $lastModified = ConvertTo-IsoStringOrNull (Get-PageXmlLastModified $px)
            if ($null -eq $lastModified) {
                $pageNode = $hierarchy.Doc.SelectSingleNode("//one:Page[@ID='$pageId']", $hierarchy.Ns)
                if ($pageNode) { $lastModified = ConvertTo-IsoStringOrNull $pageNode.lastModifiedTime }
            }
            Write-Row $stdout @{
                pageId       = $pageId
                pageXml      = $pageXml
                notebookName = $(if ($ancestors) { $ancestors.NotebookName } else { "" })
                sectionName  = $(if ($ancestors) { $ancestors.SectionName } else { "" })
                notebookId   = $(if ($ancestors) { $ancestors.NotebookId } else { "" })
                sectionId    = $(if ($ancestors) { $ancestors.SectionId } else { "" })
                lastModified = $lastModified
            }
            $count++
        }

        "CreateNewPage" {
            $sectionId = $request.sectionId
            $title = $request.title
            $bodyText = $request.bodyText

            $hierarchyBefore = Get-HierarchyXml $onenote
            $ancestors = Resolve-SectionAncestors $hierarchyBefore $sectionId
            if (-not $ancestors) {
                throw "section not found: $sectionId"
            }

            $newPageId = $null
            $onenote.CreateNewPage($sectionId, [ref]$newPageId, 0)  # 0 = npsDefault

            # Set title + body via the same UpdatePageContent pattern
            # /mnt/c/usr/WinMCP/_spike_onenote_write.ps1 validated. A
            # brand-new, just-created page has no prior content to
            # conflict with, so [DateTime]::MinValue is appropriate HERE
            # (unlike onenote_update_page, which must never use it) --
            # design.md's "Optimistic concurrency" decision is scoped to
            # updates of EXISTING pages.
            $newPageXml = ""
            $onenote.GetPageContent($newPageId, [ref]$newPageXml, 0)
            [xml]$px = $newPageXml
            $nsUri = $px.DocumentElement.NamespaceURI

            $ns = New-Object System.Xml.XmlNamespaceManager($px.NameTable)
            $ns.AddNamespace("one", $nsUri)
            $titleT = $px.SelectSingleNode("//one:Title//one:T", $ns)
            if (-not $titleT) {
                $titleEl = $px.CreateElement("one", "Title", $nsUri)
                $oe = $px.CreateElement("one", "OE", $nsUri)
                $t = $px.CreateElement("one", "T", $nsUri)
                $t.AppendChild($px.CreateCDataSection($title)) | Out-Null
                $oe.AppendChild($t) | Out-Null
                $titleEl.AppendChild($oe) | Out-Null
                $px.DocumentElement.AppendChild($titleEl) | Out-Null
            } else {
                $titleT.InnerXml = ""
                $titleT.AppendChild($px.CreateCDataSection($title)) | Out-Null
            }

            $outline = $px.CreateElement("one", "Outline", $nsUri)
            $oec = $px.CreateElement("one", "OEChildren", $nsUri)
            $oe2 = $px.CreateElement("one", "OE", $nsUri)
            $t2 = $px.CreateElement("one", "T", $nsUri)
            $t2.AppendChild($px.CreateCDataSection($bodyText)) | Out-Null
            $oe2.AppendChild($t2) | Out-Null
            $oec.AppendChild($oe2) | Out-Null
            $outline.AppendChild($oec) | Out-Null
            $px.DocumentElement.AppendChild($outline) | Out-Null

            # Strip the fetched lastModifiedTime attribute before posting:
            # UpdatePageContent PRESERVES a lastModifiedTime present in
            # the submitted XML instead of stamping the write time
            # (live-QA finding, 2026-08-27) -- leaving it in froze the
            # page's timestamp and silently disabled optimistic
            # concurrency for every later update.
            $px.DocumentElement.RemoveAttribute("lastModifiedTime")

            $onenote.UpdatePageContent($px.OuterXml, [DateTime]::MinValue)

            $finalXml = ""
            $onenote.GetPageContent($newPageId, [ref]$finalXml, 0)
            [xml]$pxFinal = $finalXml
            # Page-XML source, same reason as GetPageContent/
            # UpdatePageContent: this is the value a follow-up guarded
            # update will be compared against.
            $lastModified = ConvertTo-IsoStringOrNull (Get-PageXmlLastModified $pxFinal)
            if ($null -eq $lastModified) {
                $hierarchyAfter = Get-HierarchyXml $onenote
                $pageNode = $hierarchyAfter.Doc.SelectSingleNode("//one:Page[@ID='$newPageId']", $hierarchyAfter.Ns)
                if ($pageNode) { $lastModified = ConvertTo-IsoStringOrNull $pageNode.lastModifiedTime }
            }

            Write-Row $stdout @{
                pageId       = $newPageId
                pageXml      = $finalXml
                notebookName = $ancestors.NotebookName
                sectionName  = $ancestors.SectionName
                notebookId   = $ancestors.NotebookId
                sectionId    = $ancestors.SectionId
                lastModified = $lastModified
            }
            $count++
        }

        "UpdatePageContent" {
            $pageId = $request.pageId
            $bodyText = $request.bodyText
            $expectedLastModified = $request.expectedLastModified

            $pageXml = ""
            try {
                $onenote.GetPageContent($pageId, [ref]$pageXml, 0)
            } catch {
                throw "page not found: $pageId ($($_.Exception.Message))"
            }
            if ([string]::IsNullOrEmpty($pageXml)) {
                throw "page not found: $pageId (empty content)"
            }
            [xml]$px = $pageXml

            # Optimistic concurrency (design.md's "Optimistic concurrency"
            # decision, onenote-write-page spec's "Update Page Requires
            # Optimistic Concurrency" requirement), rebuilt on the
            # onenote/0002+0003 findings (2026-08-28):
            #
            # * SOURCE: the page XML root's own `lastModifiedTime`
            #   attribute -- the value COM's UpdatePageContent actually
            #   compares against (live-confirmed by prediction test).
            #   NEVER the hierarchy's page attributes: `dateTime` is the
            #   creation time, and both go stale indefinitely once
            #   OneNote settles a write, which made every honest update
            #   fail 0x80042010 while the pre-check happily passed the
            #   same doomed value through.
            # * COMPARISON: equality (-ne), matching COM's own semantics
            #   (hrLastModifiedDateDidNotMatch) -- a NEWER caller value is
            #   just as much a conflict as an older one, and the message
            #   says which direction so the caller knows whether to
            #   re-read (stale) or question where their value came from
            #   (newer). Values FIRST in the message, pageId last: the
            #   transport caps its stderr excerpt and the values are the
            #   diagnostic (onenote/0003 defect 3 -- the cap used to eat
            #   the one field a caller needed).
            # * ESCAPE HATCH (onenote/0005): a missing/empty
            #   expectedLastModified means the caller chose an UNGUARDED
            #   overwrite -- the one-argument UpdatePageContent call, no
            #   date check at all. OneNote's two per-page timestamps
            #   diverge minutes after a write settles, and can flicker
            #   during the unsettled window, so a caller who re-read and
            #   was still refused must have a documented way through.
            #
            # RoundtripKind + ToUniversalTime() on both parses, unchanged
            # from the 2026-08-27 fix: "Z" parses as unadjusted UTC while
            # "+00:00" adjusts to local, and the unadjusted UTC value is
            # what OneNote compares against.
            $inv = [System.Globalization.CultureInfo]::InvariantCulture
            $rtk = [System.Globalization.DateTimeStyles]::RoundtripKind
            $guarded = -not [string]::IsNullOrWhiteSpace([string]$expectedLastModified)
            $expectedDate = $null
            if ($guarded) {
                $expectedDate = [DateTime]::Parse([string]$expectedLastModified, $inv, $rtk).ToUniversalTime()
                $actualText = Get-PageXmlLastModified $px
                if ($null -ne $actualText) {
                    $actualLastModified = [DateTime]::Parse($actualText, $inv, $rtk).ToUniversalTime()
                    if ($actualLastModified -ne $expectedDate) {
                        # Message budget (onenote/0021): the transport caps its
                        # stderr excerpt at 200 chars INCLUDING the "script
                        # error: " prefix, so this whole message must fit in
                        # ~186 or the tail is cut mid-word. Rank parts by what
                        # the caller cannot reconstruct: values first, then the
                        # direction + remediation. The pageId is OMITTED
                        # entirely - the caller passed it in. Both branches end
                        # in the same remediation because a successful write can
                        # legitimately move the stored value BACKWARDS
                        # (re-converge onto the old hierarchy value), so
                        # re-reading is the fix in the NEWER direction too
                        # (onenote/0017).
                        $direction = $(if ($expectedDate -lt $actualLastModified) {
                            "page modified after your value; re-read and retry"
                        } else {
                            "value is NEWER; re-read and retry (a write can move it backwards)"
                        })
                        throw ("conflict: expected $($expectedDate.ToString('o')), " +
                               "actual $($actualLastModified.ToString('o')) - $direction")
                    }
                }
            }
            $nsUri = $px.DocumentElement.NamespaceURI
            $ns = New-Object System.Xml.XmlNamespaceManager($px.NameTable)
            $ns.AddNamespace("one", $nsUri)

            # Partial patch (design.md's "Update semantics" decision):
            # body APPENDS a new paragraph, never replaces/removes
            # existing content.
            $outline = $px.CreateElement("one", "Outline", $nsUri)
            $oec = $px.CreateElement("one", "OEChildren", $nsUri)
            $oe = $px.CreateElement("one", "OE", $nsUri)
            $t = $px.CreateElement("one", "T", $nsUri)
            $t.AppendChild($px.CreateCDataSection($bodyText)) | Out-Null
            $oe.AppendChild($t) | Out-Null
            $oec.AppendChild($oe) | Out-Null
            $outline.AppendChild($oec) | Out-Null
            $px.DocumentElement.AppendChild($outline) | Out-Null

            # Strip the fetched lastModifiedTime attribute before posting
            # (same reason as the CreateNewPage op above): submitting it
            # makes UpdatePageContent KEEP that timestamp instead of
            # stamping the write time, freezing the page's last-modified
            # and disabling conflict detection for every later update.
            $px.DocumentElement.RemoveAttribute("lastModifiedTime")

            # Guarded: the caller's value, passed through verbatim --
            # never [DateTime]::MinValue on the caller's behalf. A
            # 0x80042010 here despite the matching pre-check means the
            # page's stored value changed between this script's read and
            # COM's own comparison (OneNote's unsettled-window flicker,
            # observed live 2026-08-28) -- decoded so the caller learns
            # the cause, not just the HRESULT.
            # Unguarded: the ONE-argument call skips OneNote's date check
            # entirely -- the caller explicitly chose an unguarded
            # overwrite by omitting expectedLastModified.
            try {
                if ($guarded) {
                    $onenote.UpdatePageContent($px.OuterXml, $expectedDate)
                } else {
                    $onenote.UpdatePageContent($px.OuterXml)
                }
            } catch {
                $comMessage = $_.Exception.Message
                if ($comMessage -match "0x80042010") {
                    # Same 200-char excerpt budget as the pre-check message
                    # above (onenote/0021): no pageId, essentials only.
                    throw ("conflict: hrLastModifiedDateDidNotMatch (0x80042010) - " +
                           "stored value changed between read and write; re-read " +
                           "and retry, or omit dateExpectedLastModified for an " +
                           "unguarded overwrite")
                }
                throw
            }

            $finalXml = ""
            $onenote.GetPageContent($pageId, [ref]$finalXml, 0)
            [xml]$pxAfter = $finalXml
            $hierarchyAfter = Get-HierarchyXml $onenote
            $ancestors = Resolve-PageAncestors $hierarchyAfter $pageId
            # Post-write lastModified: the page XML's own value (the one a
            # follow-up guarded update will need). OneNote stamps it
            # lazily, so this can briefly still read the pre-write value
            # -- documented tool-description caveat, not a bridge bug.
            $lastModified = ConvertTo-IsoStringOrNull (Get-PageXmlLastModified $pxAfter)
            if ($null -eq $lastModified) {
                $pageNodeAfter = $hierarchyAfter.Doc.SelectSingleNode("//one:Page[@ID='$pageId']", $hierarchyAfter.Ns)
                if ($pageNodeAfter) { $lastModified = ConvertTo-IsoStringOrNull $pageNodeAfter.lastModifiedTime }
            }

            Write-Row $stdout @{
                pageId       = $pageId
                pageXml      = $finalXml
                notebookName = $(if ($ancestors) { $ancestors.NotebookName } else { "" })
                sectionName  = $(if ($ancestors) { $ancestors.SectionName } else { "" })
                notebookId   = $(if ($ancestors) { $ancestors.NotebookId } else { "" })
                sectionId    = $(if ($ancestors) { $ancestors.SectionId } else { "" })
                lastModified = $lastModified
            }
            $count++
        }

        default {
            throw "Unknown op: $op"
        }
    }

    # Final sentinel line: marks a complete, non-truncated stream --
    # identical contract to ps_bridge_search.ps1's own sentinel.
    $stdout.WriteLine((ConvertTo-Json -InputObject ([ordered]@{ done = $true; count = $count }) -Compress))
    $stdout.Flush()
} catch {
    [pscustomobject]@{ error = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
}
