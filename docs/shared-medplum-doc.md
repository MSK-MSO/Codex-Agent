# Shared Medplum / EHR Build Plan — read & edit it

There is ONE canonical copy of the Medplum build plan: a **Word document in the
MSO OneDrive** (`Medplum_Build_Plan.docx`). Dr. Yoo and staff co-author it in
Word for the web; the agents read and edit the *same file*. Do not fork a
second source of truth.

| Identifier | Value |
|---|---|
| Drive ID | `b!7HDlcYrkuEiHVuQCDLTRMIamaBAy42BJrJoIl8hcoZbPiYzkN90CT5Qh-gMI3C9m` |
| Item ID | `01L5ETRGBL4LQNSPUWLFFZZ3T3JT75VNX2` |
| Graph token | `bash /home/azureuser/mso-graph-token.sh` (MSO delegated, has Files.ReadWrite.All) |

## VM agents (openclaw-claude, openclaw-codex)

Use the helper on `openclaw-vm`:

    python3 /home/azureuser/medplum-doc.py pull                       # download + make a .txt read copy
    # read /home/azureuser/medplum-doc/Medplum_Build_Plan.txt
    # edit /home/azureuser/medplum-doc/Medplum_Build_Plan.docx with python-docx (preserves formatting)
    python3 /home/azureuser/medplum-doc.py push <agent> "<message>"   # upload, with a version guard

`push` uses an If-Match guard: if a human or another agent changed the doc since
your pull, the push is REFUSED so you never clobber them — pull again, redo,
push. OneDrive keeps full version history as a backstop.

## MSO Claude Code (cloud)

Either drive the helper on the VM via the dispatch-az-run-command workflow, or
hit Graph directly with the drive/item IDs above using your own Graph access:
GET /v1.0/drives/{drive}/items/{item}/content to read,
PUT .../content with If-Match: <eTag> to write.

## Rules
- Always pull immediately before editing.
- Edit the .docx with python-docx to keep formatting — never rebuild from the .txt.
- Never write secrets, tokens, AAD ids, or patient data into this doc.
- Edit when asked; don't continuously rewrite a doc humans are co-authoring.
